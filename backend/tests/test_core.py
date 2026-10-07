"""Tests for the rules that are easy to break silently: fingerprinting, dedupe,
score normalization and group assembly.

The repository tests talk to a real MongoDB on the configured URI using a
throwaway database, since dedupe depends on index behaviour that a mock would
not reproduce.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from researchlens.config import Settings, get_settings
from researchlens.documents import (
    RawPaper,
    compute_fingerprint,
    embedding_input,
    normalize_arxiv_id,
    normalize_doi,
    title_slug,
    to_document,
)
from researchlens.ml.embeddings import HashingEmbedder
from researchlens.search.live import coverage_is_thin, normalize_query
from researchlens.search.service import _citation_score, _min_max, _recency_score


# --------------------------------------------------------------------- documents


def test_doi_wins_over_arxiv_id():
    raw = RawPaper(
        title="A paper",
        source="openalex",
        doi="https://doi.org/10.1000/ABC",
        source_ids={"arxiv": "2103.00020v2"},
    )
    assert compute_fingerprint(raw) == "doi:10.1000/abc"


def test_arxiv_id_is_version_stripped():
    assert normalize_arxiv_id("http://arxiv.org/abs/1706.03762v5") == "1706.03762"
    assert normalize_arxiv_id("arXiv:2103.00020") == "2103.00020"


def test_doi_prefix_is_stripped_and_lowercased():
    assert normalize_doi("HTTPS://DOI.ORG/10.1/XY") == "10.1/xy"
    assert normalize_doi(None) is None


def test_title_slug_ignores_case_and_punctuation():
    a = title_slug("Swin-Unet: Unet-Like Pure Transformer!")
    b = title_slug("swin unet   unet like pure transformer")
    assert a == b


def test_document_shape():
    doc = to_document(
        RawPaper(
            title="  Attention Is   All You Need ",
            source="arxiv",
            abstract="x",
            authors=[{"name": "A Vaswani"}, {"name": ""}],
            published_date=date(2017, 6, 12),
            topics=["cs.CL"],
            source_ids={"arxiv": "1706.03762v5"},
        )
    )
    assert doc["title"] == "Attention Is All You Need"
    assert doc["year"] == 2017
    assert doc["authors_text"] == "A Vaswani"  # blank author dropped
    assert doc["fingerprint"] == "arxiv:1706.03762"
    assert doc["topics_text"] == "cs.CL"


def test_embedding_input_leads_with_title():
    text = embedding_input({"title": "T", "abstract": "A", "topics": ["Topic"]})
    assert text.startswith("T")
    assert "Topic" in text and "A" in text


# -------------------------------------------------------------------- embeddings


def test_hashing_embedder_is_deterministic_and_normalized():
    embedder = HashingEmbedder(dim=64)
    first = embedder.encode(["graph neural networks"])
    second = embedder.encode(["graph neural networks"])
    assert first.shape == (1, 64)
    assert pytest.approx(float((first[0] ** 2).sum()), abs=1e-5) == 1.0
    assert (first == second).all()


def test_hashing_embedder_separates_unrelated_text():
    embedder = HashingEmbedder(dim=256)
    vectors = embedder.encode(["protein folding prediction", "monetary policy inflation"])
    similarity = float(vectors[0] @ vectors[1])
    assert similarity < 0.2


def test_fallback_hybrid_search_uses_keyword_ranking():
    from researchlens.search.service import SearchService

    paper = {
        "_id": "paper-1",
        "title": "Photovoltaic cell efficiency",
        "abstract": "A study of solar cell performance.",
        "authors": [],
        "topics": ["Photovoltaics"],
        "published_date": datetime.now(timezone.utc),
        "citation_count": 0,
    }

    class Repo:
        def text_search(self, query, limit):
            return [(paper["_id"], 1.0, paper)]

    service = SearchService(
        repo=Repo(),
        embedder=HashingEmbedder(dim=64),
        settings=Settings(search_backend="local", embedding_backend="hashing"),
    )
    service._log_query = lambda response: None

    response = service.search("photovoltaic cell", mode="hybrid")

    assert response.mode == "keyword"
    assert [hit.paper["title"] for hit in response.hits] == [paper["title"]]
    assert response.top_similarity == 0.0


def test_fallback_recommendations_only_use_keyword_matches():
    from researchlens.search.recommend import RecommendationService

    paper = {
        "_id": "paper-1",
        "title": "Photovoltaic cell efficiency",
        "abstract": "A study of solar cell performance.",
        "authors": [],
        "topics": ["Photovoltaics"],
        "published_date": datetime.now(timezone.utc),
        "citation_count": 0,
    }

    class Repo:
        def text_search(self, query, limit):
            return [(paper["_id"], 1.0, paper)]

        def get_many(self, ids):
            return {}

    service = RecommendationService(
        repo=Repo(),
        embedder=HashingEmbedder(dim=64),
        settings=Settings(search_backend="local", embedding_backend="hashing"),
    )

    recommendations = service.for_query("photovoltaic cell")

    assert [group.key for group in recommendations.groups] == ["closest"]
    assert recommendations.groups[0].hits[0].paper["title"] == paper["title"]
    assert recommendations.groups[0].description == "Direct matches on your search terms."


def test_fallback_search_requires_both_terms_for_two_word_queries():
    from researchlens.search.service import SearchService

    deepfake = {
        "_id": "paper-1",
        "title": "Media Forensics and DeepFakes: An Overview",
        "abstract": "A survey of media forensics and manipulated content.",
        "authors": [],
        "topics": ["Digital Media Forensic Detection"],
        "published_date": datetime.now(timezone.utc),
        "citation_count": 952,
    }

    class Repo:
        def text_search(self, query, limit):
            return [(deepfake["_id"], 1.0, deepfake)]

    service = SearchService(
        repo=Repo(),
        embedder=HashingEmbedder(dim=64),
        settings=Settings(search_backend="local", embedding_backend="hashing"),
    )
    service._log_query = lambda response: None

    response = service.search("social media", mode="hybrid")

    assert response.mode == "keyword"
    assert response.hits == []


# ----------------------------------------------------------------------- scoring


def test_min_max_maps_to_unit_range():
    scaled = _min_max({"a": 2.0, "b": 4.0, "c": 6.0})
    assert scaled == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_min_max_handles_identical_scores():
    assert _min_max({"a": 3.0, "b": 3.0}) == {"a": 1.0, "b": 1.0}


def test_recency_halves_at_the_half_life():
    half_life = 1000.0
    when = datetime.now(timezone.utc) - timedelta(days=half_life)
    assert _recency_score(when, half_life) == pytest.approx(0.5, abs=0.01)
    assert _recency_score(None, half_life) == 0.0


def test_citation_score_is_compressed_and_capped():
    assert _citation_score(0) == 0.0
    assert _citation_score(10) < _citation_score(1000) < 1.0
    assert _citation_score(10_000_000) == 1.0


# -------------------------------------------------------------------------- live


def test_query_normalization():
    assert normalize_query("  Multimodal   LEARNING ") == "multimodal learning"


def test_thin_coverage_rules():
    settings = get_settings()
    good = settings.live_good_similarity
    needed = settings.live_min_results

    # Nothing local at all.
    assert coverage_is_thin([], settings=settings)
    # Plenty of hits, none of them close.
    assert coverage_is_thin([0.1] * 50, settings=settings)
    # Enough genuinely close papers: covered.
    assert not coverage_is_thin([good + 0.05] * needed, settings=settings)


def test_one_lucky_hit_is_not_coverage():
    """The photovoltaic case: a neighbouring corpus always has something adjacent.

    A single decent match surrounded by weak ones must still count as thin,
    otherwise the query is answered out of the wrong literature.
    """
    settings = get_settings()
    similarities = [0.49] + [0.3] * 20
    assert coverage_is_thin(similarities, settings=settings)


# -------------------------------------------------------------------- repository

pymongo = pytest.importorskip("pymongo")


@pytest.fixture
def repo():
    from pymongo import MongoClient

    from researchlens.repository import PaperRepository

    settings = get_settings()
    client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception:  # pragma: no cover - environment without Mongo
        pytest.skip("MongoDB is not reachable")

    name = "researchlens_test"
    client.drop_database(name)
    database = client[name]
    database["papers"].create_index("fingerprint", unique=True)
    yield PaperRepository(database)
    client.drop_database(name)
    client.close()


def test_same_paper_from_two_sources_collapses_in_one_batch(repo):
    """arXiv and OpenAlex return the same work in one fetch under different ids."""
    batch = [
        RawPaper(title="Swin-Unet: Unet-Like Pure Transformer", source="arxiv", source_ids={"arxiv": "2105.05537"}),
        RawPaper(title="Swin-Unet: Unet-like pure transformer", source="openalex", doi="10.1/swin"),
    ]
    result = repo.upsert_many(batch)
    assert repo.count() == 1
    assert result.created == 1

    stored = repo.col.find_one({})
    # The DOI is the stronger identifier, so it becomes the primary fingerprint.
    assert stored["fingerprint"] == "doi:10.1/swin"
    assert "arxiv:2105.05537" in stored["alt_fingerprints"]


def test_reingest_updates_instead_of_duplicating(repo):
    raw = RawPaper(title="One Paper", source="arxiv", source_ids={"arxiv": "1234.5678"})
    repo.upsert_many([raw])
    repo.upsert_many([raw])
    assert repo.count() == 1


def test_citation_count_never_regresses(repo):
    repo.upsert_many([RawPaper(title="Cited", source="openalex", doi="10.1/c", citation_count=500)])
    repo.upsert_many([RawPaper(title="Cited", source="openalex", doi="10.1/c", citation_count=12)])
    assert repo.col.find_one({})["citation_count"] == 500


def test_longer_abstract_wins(repo):
    repo.upsert_many([RawPaper(title="P", source="arxiv", doi="10.1/p", abstract="short")])
    repo.upsert_many(
        [RawPaper(title="P", source="openalex", doi="10.1/p", abstract="a much longer abstract")]
    )
    assert repo.col.find_one({})["abstract"] == "a much longer abstract"


def test_empty_values_do_not_overwrite_stored_ones(repo):
    repo.upsert_many([RawPaper(title="P", source="arxiv", doi="10.1/p", venue="NeurIPS")])
    repo.upsert_many([RawPaper(title="P", source="openalex", doi="10.1/p", venue=None)])
    assert repo.col.find_one({})["venue"] == "NeurIPS"
