"""Health and stats endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..db import is_atlas, ping
from ..ingest.service import IngestService
from ..ml.vector_index import get_vector_index
from ..repository import PaperRepository
from ..schemas import HealthOut, StatsOut, TopicCount
from .deps import ingest_dep, repo_dep, settings_dep

router = APIRouter(tags=["system"])


@router.get("/api/health", response_model=HealthOut)
def health(
    repo: PaperRepository = Depends(repo_dep),
    service: IngestService = Depends(ingest_dep),
    settings: Settings = Depends(settings_dep),
) -> HealthOut:
    alive = ping(settings)
    stats = repo.stats(service.embedder.name) if alive else {"papers": 0, "embedded": 0}
    corpus_model = repo.dominant_embedding_model() if alive else None
    degraded = service.embedder.is_fallback or (
        corpus_model is not None and corpus_model != service.embedder.name
    )
    return HealthOut(
        status="degraded" if (not alive or degraded) else "ok",
        mongodb=alive,
        search_backend="atlas" if alive and is_atlas(settings) else "local",
        embedding_model=service.embedder.name,
        embedding_dim=service.embedder.dim,
        papers=stats.get("papers", 0),
        embedded=stats.get("embedded", 0),
        embedding_degraded=degraded,
        corpus_embedding_model=corpus_model,
    )


@router.get("/api/stats", response_model=StatsOut)
def stats(
    repo: PaperRepository = Depends(repo_dep),
    service: IngestService = Depends(ingest_dep),
    settings: Settings = Depends(settings_dep),
) -> StatsOut:
    base = repo.stats(service.embedder.name)
    index = get_vector_index(repo, service.embedder.name, settings)
    return StatsOut(
        papers=base["papers"],
        embedded=base["embedded"],
        by_source=base["by_source"],
        top_topics=[TopicCount(**t) for t in repo.distinct_topics(12)],
        embedding_model=service.embedder.name,
        search_backend="atlas" if is_atlas(settings) else "local",
        index_backend=index.backend,
        indexed_vectors=index.size(),
    )
