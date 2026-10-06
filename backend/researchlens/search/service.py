"""Search: keyword, semantic, and the hybrid combiner.

Three modes share one result shape so the UI never branches on mode:

* keyword  - Mongo text index (or Atlas Search on Atlas). Exact-term recall.
* semantic - query embedding vs. paper embeddings, cosine. Meaning over terms.
* hybrid   - normalized fusion of both, plus small recency and citation nudges.

Every result carries `score_parts`, which is what makes ranking explainable in
the UI instead of a black box.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..db import SEARCH_LOG, get_db, is_atlas
from ..logging_conf import get_logger
from ..ml.embeddings import Embedder, get_embedder
from ..ml.vector_index import get_vector_index
from ..repository import PaperRepository

log = get_logger(__name__)

MODES = ("keyword", "semantic", "hybrid")


@dataclass(slots=True)
class SearchHit:
    paper: dict[str, Any]
    score: float
    score_parts: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    # Raw cosine against the query, before any normalization. `score` and
    # `score_parts` are relative to the result set, so they say nothing about
    # absolute quality; this does, and it is what relevance gates read.
    similarity: float = 0.0


@dataclass(slots=True)
class SearchResponse:
    query: str
    mode: str
    total: int
    took_ms: int
    hits: list[SearchHit] = field(default_factory=list)
    backend: str = "local"
    # Best raw cosine in the candidate pool, 0.0 when nothing was embedded.
    top_similarity: float = 0.0


class SearchService:
    def __init__(
        self,
        repo: PaperRepository | None = None,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo or PaperRepository()
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder(self.settings)
        return self._embedder

    # ------------------------------------------------------------------ public

    def search(self, query: str, mode: str = "hybrid", limit: int = 20) -> SearchResponse:
        query = (query or "").strip()
        mode = mode if mode in MODES else "hybrid"
        limit = max(1, min(limit, self.settings.max_page_size))
        started = time.perf_counter()

        if not query:
            return SearchResponse(query=query, mode=mode, total=0, took_ms=0, hits=[])

        fallback = self.embedder.is_fallback
        if fallback and mode != "keyword":
            mode = "keyword"

        if mode == "keyword":
            hits = self._keyword(query, limit)
        elif mode == "semantic":
            hits = self._semantic(query, limit)
        else:
            hits = self._hybrid(query, limit)

        # Measured on the whole corpus, not on the surviving hits, so a query
        # the corpus cannot answer still reports how far off the nearest paper is.
        top_similarity = 0.0 if fallback else self._best_similarity(query)

        took_ms = int((time.perf_counter() - started) * 1000)
        response = SearchResponse(
            query=query,
            mode=mode,
            total=len(hits),
            took_ms=took_ms,
            hits=hits,
            backend="atlas" if is_atlas(self.settings) else "local",
            top_similarity=round(top_similarity, 4),
        )
        self._log_query(response)
        return response

    def similar_to_paper(self, paper_id: str, limit: int = 10) -> list[SearchHit]:
        """Related-paper discovery: nearest neighbours of a paper's own vector."""
        embedding = self.repo.get_vector(paper_id)
        if not embedding or not embedding.get("vector"):
            return []
        index = get_vector_index(self.repo, self.embedder.name, self.settings)
        import numpy as np

        raw = index.search(np.asarray(embedding["vector"], dtype="float32"), limit + 1)
        raw = [(pid, score) for pid, score in raw if pid != paper_id][:limit]
        docs = self.repo.get_many([pid for pid, _ in raw])
        hits: list[SearchHit] = []
        for pid, score in raw:
            doc = docs.get(pid)
            if not doc:
                continue
            hits.append(
                SearchHit(
                    paper=doc,
                    score=round(float(score), 4),
                    score_parts={"semantic": round(float(score), 4)},
                    reason="Similar content and methodology",
                )
            )
        return hits

    # ----------------------------------------------------------------- internals

    def _keyword(self, query: str, limit: int) -> list[SearchHit]:
        raw = (
            self.repo.atlas_text_search(query, limit)
            if is_atlas(self.settings)
            else self.repo.text_search(query, limit)
        )
        if not raw:
            return []
        scores = {pid: score for pid, score, _ in raw}
        normalized = _min_max({k: v for k, v in scores.items()})
        return [
            SearchHit(
                paper=doc,
                score=round(normalized.get(pid, 0.0), 4),
                score_parts={"keyword": round(normalized.get(pid, 0.0), 4)},
                reason=_keyword_reason(query, doc),
            )
            for pid, _score, doc in raw
        ]

    def _best_similarity(self, query: str) -> float:
        """Highest raw cosine anywhere in the corpus for this query."""
        return max(self._semantic_scores(query, 1).values(), default=0.0)

    def _semantic_scores(self, query: str, limit: int) -> dict[str, float]:
        vector = self.embedder.encode_one(query)
        index = get_vector_index(self.repo, self.embedder.name, self.settings)
        return {pid: score for pid, score in index.search(vector, limit)}

    def _semantic(self, query: str, limit: int) -> list[SearchHit]:
        scores = self._semantic_scores(query, limit)
        if not scores:
            return []
        docs = self.repo.get_many(list(scores))
        hits = [
            SearchHit(
                paper=docs[pid],
                score=round(float(score), 4),
                score_parts={"semantic": round(float(score), 4)},
                reason="Semantically close to your query",
                similarity=float(score),
            )
            for pid, score in scores.items()
            if pid in docs
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return _apply_floor(hits, self.settings.search_min_similarity)[:limit]

    def _hybrid(self, query: str, limit: int) -> list[SearchHit]:
        """Fuse both signals over a wider candidate pool, then re-rank."""
        pool = max(limit * 4, 40)
        semantic = self._semantic_scores(query, pool)
        keyword_raw = (
            self.repo.atlas_text_search(query, pool)
            if is_atlas(self.settings)
            else self.repo.text_search(query, pool)
        )
        keyword = _min_max({pid: score for pid, score, _ in keyword_raw})
        semantic_n = _min_max(semantic)

        candidate_docs: dict[str, dict[str, Any]] = {pid: doc for pid, _s, doc in keyword_raw}
        missing = [pid for pid in semantic if pid not in candidate_docs]
        candidate_docs.update(self.repo.get_many(missing))

        w_sem = self.settings.hybrid_semantic_weight
        w_kw = self.settings.hybrid_keyword_weight
        w_rec = self.settings.recency_weight
        w_cit = self.settings.citation_weight
        # Keep the final score in [0,1] whatever the configured weights are.
        w_total = (w_sem + w_kw + w_rec + w_cit) or 1.0
        hits: list[SearchHit] = []
        for pid, doc in candidate_docs.items():
            sem = semantic_n.get(pid, 0.0)
            kw = keyword.get(pid, 0.0)
            recency = _recency_score(doc.get("published_date"), self.settings.recency_half_life_days)
            citations = _citation_score(doc.get("citation_count", 0))
            score = (
                w_sem * sem + w_kw * kw + w_rec * recency + w_cit * citations
            ) / w_total
            hits.append(
                SearchHit(
                    paper=doc,
                    score=round(score, 4),
                    score_parts={
                        "semantic": round(sem, 4),
                        "keyword": round(kw, 4),
                        "recency": round(recency, 4),
                        "citations": round(citations, 4),
                    },
                    reason=_hybrid_reason(sem, kw, doc, query),
                    similarity=float(semantic.get(pid, 0.0)),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        # A keyword hit passes without meeting the cosine floor: an exact term
        # match is evidence in its own right.
        kept = [
            h
            for h in hits
            if h.similarity >= self.settings.search_min_similarity
            or h.score_parts.get("keyword", 0.0) > 0.0
        ]
        return kept[:limit]

    def _log_query(self, response: SearchResponse) -> None:
        try:
            get_db(self.settings)[SEARCH_LOG].insert_one(
                {
                    "query": response.query,
                    "mode": response.mode,
                    "result_count": response.total,
                    "took_ms": response.took_ms,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        except Exception:  # logging must never fail a search
            log.debug("search log write failed", exc_info=True)


# --------------------------------------------------------------------- scoring


def _apply_floor(hits: list[SearchHit], floor: float) -> list[SearchHit]:
    """Drop hits that are not actually close.

    Vector search always returns the K nearest neighbours however distant they
    are, so without an absolute floor an unanswerable query still comes back
    full of confident-looking results.
    """
    return [h for h in hits if h.similarity >= floor]


def _min_max(scores: dict[str, float]) -> dict[str, float]:
    """Scale to [0,1]. Different signals are not comparable raw."""
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if math.isclose(high, low):
        return {k: 1.0 for k in scores}
    span = high - low
    return {k: (v - low) / span for k, v in scores.items()}


def _recency_score(published: Any, half_life_days: float) -> float:
    """Exponential decay - a 3-year-old paper scores 0.5 by default."""
    if not published:
        return 0.0
    if not isinstance(published, datetime):
        return 0.0
    now = datetime.now(timezone.utc)
    when = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
    age_days = max((now - when).days, 0)
    return float(0.5 ** (age_days / max(half_life_days, 1.0)))


def _citation_score(count: int) -> float:
    """log-compressed: 10k citations is not 1000x better than 10."""
    return float(min(math.log1p(max(count, 0)) / math.log1p(10000), 1.0))


def _overlapping_terms(query: str, doc: dict[str, Any]) -> list[str]:
    words = {w for w in query.lower().split() if len(w) > 3}
    haystack = f"{doc.get('title', '')} {doc.get('abstract', '')}".lower()
    return [w for w in words if w in haystack]


def _keyword_reason(query: str, doc: dict[str, Any]) -> str:
    terms = _overlapping_terms(query, doc)
    if terms:
        return "Matches terms: " + ", ".join(sorted(terms)[:4])
    return "Keyword match"


def _hybrid_reason(sem: float, kw: float, doc: dict[str, Any], query: str) -> str:
    """Explainability is a product requirement, not polish."""
    parts: list[str] = []
    if sem >= 0.6 and kw >= 0.6:
        parts.append("Strong topical and term match")
    elif sem >= 0.6:
        parts.append("Semantically close to your query")
    elif kw >= 0.6:
        terms = _overlapping_terms(query, doc)
        parts.append("Matches terms: " + ", ".join(sorted(terms)[:3]) if terms else "Keyword match")
    else:
        parts.append("Related to your query")

    topics = doc.get("topics") or []
    if topics:
        parts.append(f"in {topics[0]}")
    if int(doc.get("citation_count") or 0) >= 500:
        parts.append(f"{doc['citation_count']:,} citations")
    return " · ".join(parts)


def summarize_hits(hits: Sequence[SearchHit]) -> dict[str, Any]:  # pragma: no cover - debug aid
    return {"count": len(hits), "top": [h.paper.get("title") for h in hits[:3]]}
