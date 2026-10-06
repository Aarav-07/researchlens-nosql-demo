"""Paper browsing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings
from ..repository import PaperRepository
from ..schemas import PaperListOut, PaperOut, SearchHitOut, TopicCount
from ..search.service import SearchService
from .deps import repo_dep, search_dep, settings_dep

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("", response_model=PaperListOut)
def list_papers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: str | None = None,
    topic: str | None = None,
    sort: str = Query("date", pattern="^(date|citations|added)$"),
    repo: PaperRepository = Depends(repo_dep),
) -> PaperListOut:
    docs, total = repo.list_papers(
        limit=limit, offset=offset, source=source, topic=topic, sort=sort
    )
    return PaperListOut(
        total=total, limit=limit, offset=offset, items=[PaperOut.from_doc(d) for d in docs]
    )


@router.get("/topics", response_model=list[TopicCount])
def list_topics(
    limit: int = Query(30, ge=1, le=200),
    repo: PaperRepository = Depends(repo_dep),
) -> list[TopicCount]:
    return [TopicCount(**t) for t in repo.distinct_topics(limit)]


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(
    paper_id: str,
    include_full_text: bool = False,
    repo: PaperRepository = Depends(repo_dep),
) -> PaperOut:
    doc = repo.get(paper_id, include_full_text=include_full_text)
    if not doc:
        raise HTTPException(status_code=404, detail=f"paper {paper_id} not found")
    return PaperOut.from_doc(doc)


@router.get("/{paper_id}/similar", response_model=list[SearchHitOut])
def similar_papers(
    paper_id: str,
    limit: int = Query(10, ge=1, le=50),
    repo: PaperRepository = Depends(repo_dep),
    service: SearchService = Depends(search_dep),
    settings: Settings = Depends(settings_dep),
) -> list[SearchHitOut]:
    if not repo.get(paper_id):
        raise HTTPException(status_code=404, detail=f"paper {paper_id} not found")
    hits = service.similar_to_paper(paper_id, limit=limit)
    return [
        SearchHitOut(
            paper=PaperOut.from_doc(h.paper),
            score=h.score,
            score_parts=h.score_parts,
            reason=h.reason,
            similarity=h.similarity,
        )
        for h in hits
    ]
