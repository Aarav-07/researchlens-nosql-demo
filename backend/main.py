"""ResearchLens API entry point.

Run:
    cd backend
    uvicorn main:app --reload --port 8011

Docs: http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from researchlens import __version__
from researchlens.api import (
    routes_discover,
    routes_files,
    routes_ingest,
    routes_papers,
    routes_search,
    routes_system,
)
from researchlens.config import get_settings
from researchlens.db import close_client, ensure_atlas_search_indexes, ensure_indexes, is_atlas, ping
from researchlens.logging_conf import configure_logging, get_logger
from researchlens.sources import SourceError, available_sources

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("researchlens.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify Mongo, ensure indexes. Shutdown: close the client.

    A dead database is logged but does not stop the process - /api/health then
    reports `degraded`, which is more useful than a crash loop.
    """
    log.info("starting %s v%s", settings.app_name, __version__)
    if ping(settings):
        ensure_indexes(settings)
        if is_atlas(settings):
            from researchlens.ml.embeddings import get_embedder

            ensure_atlas_search_indexes(get_embedder(settings).dim, settings)
        log.info("MongoDB ready (backend=%s)", "atlas" if is_atlas(settings) else "local")
    else:
        log.error("MongoDB unreachable at startup - API will report degraded")
    log.info("sources available: %s", ", ".join(available_sources()))
    try:
        yield
    finally:
        close_client()
        log.info("shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Research intelligence API: multi-source paper ingest, semantic and hybrid "
        "search, and related-paper discovery."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SourceError)
async def source_error_handler(request: Request, exc: SourceError) -> JSONResponse:
    """Upstream provider failures are 502s, not 500s."""
    log.warning("source error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc), "source": exc.source})


app.include_router(routes_system.router)
app.include_router(routes_discover.router)
app.include_router(routes_search.router)
app.include_router(routes_papers.router)
app.include_router(routes_files.router)
app.include_router(routes_ingest.router)


@app.get("/", tags=["system"])
def root() -> dict[str, object]:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "endpoints": [
            "GET  /api/health",
            "GET  /api/stats",
            "GET  /api/discover?q=&mode=&limit=&live=true  (search + live fetch + recommendations)",
            "GET  /api/recommend?q=",
            "GET  /api/search?q=&mode=hybrid|semantic|keyword&limit=",
            "GET  /api/papers?limit=&offset=&source=&topic=&sort=",
            "GET  /api/papers/topics",
            "GET  /api/papers/{id}",
            "GET  /api/papers/{id}/similar",
            "GET  /api/papers/{id}/file?download=false  (stream the PDF in-app)",
            "GET  /api/ingest/sources",
            "POST /api/ingest",
            "POST /api/ingest/embed",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8011,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
