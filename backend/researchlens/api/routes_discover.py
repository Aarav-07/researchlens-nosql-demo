"""Discovery endpoint: one call per user search.

`GET /api/discover` does what the product promises in a single request: search
locally, fetch from the sources when coverage is thin, then return ranked results
plus labelled recommendation groups. The plain `/api/search` endpoint stays as
the fast, local-only path (useful for as-you-type querying).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from ..schemas import (
    DiscoverOut,
    LiveFetchOut,
    PaperOut,
    RecommendationGroupOut,
    RecommendationsOut,
    SearchHitOut,
    SearchResponseOut,
    SourceOutcomeOut,
)
from ..search.discovery import DiscoveryService
from ..search.recommend import RecommendationSet
from ..search.service import SearchHit, SearchResponse
from .deps import discovery_dep, recommender_dep

router = APIRouter(prefix="/api", tags=["discover"])


def _hit_out(hit: SearchHit) -> SearchHitOut:
    return SearchHitOut(
        paper=PaperOut.from_doc(hit.paper),
        score=hit.score,
        score_parts=hit.score_parts,
        reason=hit.reason,
        similarity=hit.similarity,
    )


def _search_out(result: SearchResponse) -> SearchResponseOut:
    return SearchResponseOut(
        query=result.query,
        mode=result.mode,
        total=result.total,
        took_ms=result.took_ms,
        backend=result.backend,
        top_similarity=result.top_similarity,
        hits=[_hit_out(h) for h in result.hits],
    )


def _rec_out(recs: RecommendationSet | None) -> RecommendationsOut | None:
    if recs is None:
        return None
    return RecommendationsOut(
        query=recs.query,
        took_ms=recs.took_ms,
        considered=recs.considered,
        groups=[
            RecommendationGroupOut(
                key=group.key,
                title=group.title,
                description=group.description,
                hits=[_hit_out(h) for h in group.hits],
            )
            for group in recs.groups
        ],
    )


@router.get("/discover", response_model=DiscoverOut)
def discover(
    q: str = Query(..., min_length=2, max_length=500, description="Natural-language query"),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(25, ge=1, le=100),
    live: bool = Query(True, description="Fetch from sources when local coverage is thin"),
    recommend: bool = Query(True, description="Include grouped recommendations"),
    service: DiscoveryService = Depends(discovery_dep),
) -> DiscoverOut:
    result = service.discover(q, mode=mode, limit=limit, live=live, recommend=recommend)

    live_out = None
    if result.live_fetch:
        payload = result.live_fetch
        live_out = LiveFetchOut(
            fetched=payload["fetched"],
            created=payload["created"],
            updated=payload["updated"],
            embedded=payload["embedded"],
            sources=[SourceOutcomeOut(**s) for s in payload["sources"]],
        )

    return DiscoverOut(
        search=_search_out(result.search),
        recommendations=_rec_out(result.recommendations),
        live_fetch=live_out,
        notes=result.notes,
    )


@router.get("/recommend", response_model=RecommendationsOut)
def recommend_for_query(
    q: str = Query(..., min_length=2, max_length=500),
    service=Depends(recommender_dep),
) -> RecommendationsOut:
    """Recommendations only, against the corpus as it already stands."""
    out = _rec_out(service.for_query(q))
    assert out is not None  # for_query always returns a set
    return out


__all__ = ["router", "asdict"]
