"""Recommendation engine.

The product problem is not "return 500 matches". It is "given what I am working
on, which handful should I read, and in what role". So recommendations come back
as labelled groups rather than one long list, and every item states why it is
there:

* closest      - highest hybrid relevance. The direct answer.
* recent       - published recently and still close. What changed lately.
* foundational - older and heavily cited. What everyone in this area cites.
* adjacent     - semantically close but sharing few of the query's words. This is
                 the group that surfaces "deep learning recommenders" for a
                 "neural collaborative filtering" query: the same idea under a
                 different vocabulary, which keyword search structurally cannot
                 find.

One paper appears in exactly one group (priority order above), so the reader
never sees the same title four times.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ..config import Settings, get_settings
from ..logging_conf import get_logger
from ..ml.embeddings import Embedder, get_embedder
from ..ml.vector_index import get_vector_index
from ..repository import PaperRepository
from .service import SearchHit, _citation_score, _min_max, _overlapping_terms, _recency_score

log = get_logger(__name__)

GROUP_ORDER = ("closest", "recent", "foundational", "adjacent")

GROUP_META: dict[str, dict[str, str]] = {
    "closest": {
        "title": "Closest to your query",
        "description": "Best combined match on meaning and terms.",
    },
    "recent": {
        "title": "Recent work",
        "description": "Published lately and still close to the query.",
    },
    "foundational": {
        "title": "Foundational",
        "description": "Older, heavily cited work this area builds on.",
    },
    "adjacent": {
        "title": "Adjacent vocabulary",
        "description": "Same idea described in different words, which keyword search misses.",
    },
}


@dataclass(slots=True)
class RecommendationGroup:
    key: str
    title: str
    description: str
    hits: list[SearchHit] = field(default_factory=list)


@dataclass(slots=True)
class RecommendationSet:
    query: str
    took_ms: int
    considered: int
    groups: list[RecommendationGroup] = field(default_factory=list)
    live_fetch: dict[str, Any] | None = None


class RecommendationService:
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

    def for_query(
        self, query: str, live_fetch: dict[str, Any] | None = None
    ) -> RecommendationSet:
        started = time.perf_counter()
        query = (query or "").strip()
        if not query:
            return RecommendationSet(query=query, took_ms=0, considered=0, groups=[])

        pool = self.settings.rec_candidate_pool
        fallback = self.embedder.is_fallback
        if fallback:
            semantic = {}
        else:
            vector = self.embedder.encode_one(query)
            index = get_vector_index(self.repo, self.embedder.name, self.settings)
            semantic = {pid: score for pid, score in index.search(vector, pool)}

        keyword_raw = self.repo.text_search(query, pool)
        keyword = _min_max({pid: score for pid, score, _doc in keyword_raw})

        docs: dict[str, dict[str, Any]] = {pid: doc for pid, _s, doc in keyword_raw}
        docs.update(self.repo.get_many([pid for pid in semantic if pid not in docs]))
        if not docs:
            return RecommendationSet(
                query=query,
                took_ms=int((time.perf_counter() - started) * 1000),
                considered=0,
                groups=[],
                live_fetch=live_fetch,
            )

        semantic_n = _min_max(semantic)
        scored = [
            _score_candidate(doc, semantic.get(pid, 0.0), semantic_n.get(pid, 0.0), keyword.get(pid, 0.0), query, self.settings)
            for pid, doc in docs.items()
        ]

        groups = self._assemble(scored, query)
        took_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "recommend %r: %d candidates -> %s",
            query,
            len(scored),
            {g.key: len(g.hits) for g in groups},
        )
        return RecommendationSet(
            query=query,
            took_ms=took_ms,
            considered=len(scored),
            groups=groups,
            live_fetch=live_fetch,
        )

    # ----------------------------------------------------------------- grouping

    def _assemble(self, scored: list["_Candidate"], query: str) -> list[RecommendationGroup]:
        size = self.settings.rec_group_size
        recent_cutoff = datetime.now(timezone.utc) - timedelta(
            days=30 * self.settings.rec_recent_months
        )
        min_citations = self.settings.rec_foundational_min_citations
        min_sim = self.settings.rec_min_similarity
        min_sim_foundational = self.settings.rec_foundational_min_similarity
        min_sim_adjacent = self.settings.rec_adjacent_min_similarity

        taken: set[str] = set()
        groups: list[RecommendationGroup] = []

        def emit(key: str, candidates: Iterable["_Candidate"], reason_fn) -> None:
            hits: list[SearchHit] = []
            for cand in candidates:
                if cand.paper_id in taken:
                    continue
                hits.append(
                    SearchHit(
                        paper=cand.doc,
                        score=round(cand.relevance, 4),
                        score_parts=cand.parts,
                        reason=reason_fn(cand),
                        similarity=round(cand.semantic_raw, 4),
                    )
                )
                taken.add(cand.paper_id)
                if len(hits) >= size:
                    break
            if hits:
                meta = GROUP_META[key]
                description = meta["description"]
                if key == "closest" and self.embedder.is_fallback:
                    description = "Direct matches on your search terms."
                groups.append(
                    RecommendationGroup(
                        key=key, title=meta["title"], description=description, hits=hits
                    )
                )

        # closest: straight hybrid relevance, but only among candidates that
        # actually match. A keyword hit qualifies on its own.
        closest = [
            c
            for c in scored
            if c.semantic_raw >= self.settings.search_min_similarity or c.keyword > 0.0
        ]
        emit(
            "closest",
            sorted(closest, key=lambda c: c.relevance, reverse=True),
            lambda c: c.default_reason,
        )

        # recent: close enough, and new
        recent = [
            c
            for c in scored
            if c.published and c.published >= recent_cutoff and c.semantic_raw >= min_sim
        ]
        # Ordered strictly by date: the group's job is "what changed lately", so
        # the visible order has to be the one the reader can verify at a glance.
        emit(
            "recent",
            sorted(recent, key=lambda c: c.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True),
            lambda c: f"Published {c.published.strftime('%b %Y')} and close to your query"
            if c.published
            else c.default_reason,
        )

        # foundational: older and widely cited
        foundational = [
            c
            for c in scored
            if c.citations >= min_citations
            and (c.published is None or c.published < recent_cutoff)
            and c.semantic_raw >= min_sim_foundational
        ]
        # Ordered by citations, which is the number each card states.
        emit(
            "foundational",
            sorted(foundational, key=lambda c: c.citations, reverse=True),
            lambda c: f"Cited {c.citations:,} times in this area",
        )

        # adjacent: strong meaning match, weak term overlap
        adjacent = [
            c
            for c in scored
            if c.semantic_raw >= min_sim_adjacent and c.keyword <= 0.2 and c.term_overlap <= 1
        ]
        emit(
            "adjacent",
            sorted(adjacent, key=lambda c: c.semantic_raw, reverse=True),
            lambda c: "Same idea, different vocabulary"
            + (f" · {c.doc['topics'][0]}" if c.doc.get("topics") else ""),
        )

        return [g for g in groups if g.hits]


@dataclass(slots=True)
class _Candidate:
    paper_id: str
    doc: dict[str, Any]
    semantic_raw: float
    keyword: float
    recency: float
    citations: int
    citation_score: float
    relevance: float
    term_overlap: int
    published: datetime | None
    parts: dict[str, float]
    default_reason: str


def _score_candidate(
    doc: dict[str, Any],
    semantic_raw: float,
    semantic_norm: float,
    keyword: float,
    query: str,
    settings: Settings,
) -> _Candidate:
    published = doc.get("published_date")
    if published is not None and not isinstance(published, datetime):
        published = None
    citations = int(doc.get("citation_count") or 0)
    recency = _recency_score(published, settings.recency_half_life_days)
    citation_score = _citation_score(citations)

    w_sem = settings.hybrid_semantic_weight
    w_kw = settings.hybrid_keyword_weight
    w_rec = settings.recency_weight
    w_cit = settings.citation_weight
    total = (w_sem + w_kw + w_rec + w_cit) or 1.0
    relevance = (
        w_sem * semantic_norm + w_kw * keyword + w_rec * recency + w_cit * citation_score
    ) / total

    overlap = _overlapping_terms(query, doc)
    parts = {
        "semantic": round(semantic_norm, 4),
        "keyword": round(keyword, 4),
        "recency": round(recency, 4),
        "citations": round(citation_score, 4),
    }

    if semantic_norm >= 0.6 and keyword >= 0.6:
        reason = "Strong match on both meaning and terms"
    elif semantic_norm >= 0.6:
        reason = "Close on meaning"
    elif overlap:
        reason = "Matches terms: " + ", ".join(sorted(overlap)[:3])
    else:
        reason = "Related to your query"
    if doc.get("topics"):
        reason = f"{reason} · {doc['topics'][0]}"

    return _Candidate(
        paper_id=doc["_id"],
        doc=doc,
        semantic_raw=float(semantic_raw),
        keyword=float(keyword),
        recency=recency,
        citations=citations,
        citation_score=citation_score,
        relevance=relevance,
        term_overlap=len(overlap),
        published=published,
        parts=parts,
        default_reason=reason,
    )


def best_local_score(hits: list[SearchHit]) -> float:
    """Best raw cosine in a result set.

    Never read `score` or `score_parts` here: both are min-max normalized within
    the result set, so the top hit always reads 1.0 and any threshold against
    them is meaningless.
    """
    return max((h.similarity for h in hits), default=0.0)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value if not math.isnan(value) else 0.0))
