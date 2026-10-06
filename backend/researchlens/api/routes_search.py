"""Search endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..schemas import PaperOut, SearchHitOut, SearchResponseOut
from ..search.service import MODES, SearchService
from .deps import search_dep

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponseOut)
def search(
    q: str = Query(..., min_length=1, max_length=500, description="Natural-language query"),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(20, ge=1, le=100),
    service: SearchService = Depends(search_dep),
) -> SearchResponseOut:
    result = service.search(q, mode=mode, limit=limit)
    return SearchResponseOut(
        query=result.query,
        mode=result.mode,
        total=result.total,
        took_ms=result.took_ms,
        backend=result.backend,
        top_similarity=result.top_similarity,
        hits=[
            SearchHitOut(
                paper=PaperOut.from_doc(h.paper),
                score=h.score,
                score_parts=h.score_parts,
                reason=h.reason,
                similarity=h.similarity,
            )
            for h in result.hits
        ],
    )


@router.get("/modes", response_model=list[str])
def search_modes() -> list[str]:
    return list(MODES)
