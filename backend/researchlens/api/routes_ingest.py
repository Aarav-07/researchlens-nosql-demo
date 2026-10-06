"""Ingest and embedding endpoints."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from ..ingest.service import IngestService
from ..ml.vector_index import get_vector_index
from ..schemas import (
    EmbedRequest,
    EmbedResponseOut,
    IngestRequest,
    IngestResponseOut,
    SourceOutcomeOut,
)
from ..sources import available_sources
from .deps import ingest_dep

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/sources", response_model=list[str])
def sources() -> list[str]:
    return available_sources()


@router.post("", response_model=IngestResponseOut)
def ingest(
    payload: IngestRequest,
    service: IngestService = Depends(ingest_dep),
) -> IngestResponseOut:
    if payload.sources:
        unknown = [s for s in payload.sources if s not in available_sources()]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown sources: {', '.join(unknown)}; have: {', '.join(available_sources())}",
            )

    report = service.ingest_query(
        query=payload.query,
        sources=payload.sources,
        limit_per_source=payload.limit_per_source,
        sort=payload.sort,
        embed=payload.embed,
    )

    if report.fetched == 0 and all(s.status == "error" for s in report.sources):
        detail = "; ".join(f"{s.source}: {s.error}" for s in report.sources)
        raise HTTPException(status_code=502, detail=f"all sources failed - {detail}")

    return IngestResponseOut(
        query=report.query,
        requested=report.requested,
        fetched=report.fetched,
        created=report.created,
        updated=report.updated,
        embedded=report.embedded,
        sources=[SourceOutcomeOut(**asdict(s)) for s in report.sources],
    )


@router.post("/embed", response_model=EmbedResponseOut)
def embed_backlog(
    payload: EmbedRequest | None = None,
    service: IngestService = Depends(ingest_dep),
) -> EmbedResponseOut:
    """Backfill vectors for papers missing them. Safe to call repeatedly."""
    limit = payload.limit if payload else None
    count = service.backfill_embeddings(limit=limit)
    index = get_vector_index(service.repo, service.embedder.name, service.settings)
    return EmbedResponseOut(
        embedded=count,
        model=service.embedder.name,
        dim=service.embedder.dim,
        index_backend=index.backend,
        indexed_vectors=index.size(),
    )
