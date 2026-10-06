"""In-app PDF delivery.

Papers live on other people's servers, and those servers block cross-origin
embedding, so the browser cannot render them directly inside the page. This
route streams the PDF through the API, which makes both inline reading and
one-click download work without the user leaving ResearchLens.

Safety: the URL is never taken from the request. It comes from the stored paper
record, must be http(s), and the response must look like a PDF. That keeps this
from becoming an open proxy or an SSRF hole.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..config import Settings
from ..logging_conf import get_logger
from ..repository import PaperRepository
from ..schemas import PaperFileInfoOut
from .deps import repo_dep, settings_dep

log = get_logger(__name__)
router = APIRouter(prefix="/api/papers", tags=["papers"])

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
_ALLOWED_SCHEMES = ("http", "https")
_PDF_CONTENT_TYPES = ("application/pdf", "application/octet-stream", "binary/octet-stream")


def resolve_pdf_url(paper: dict) -> str | None:
    """Best available PDF for a paper.

    arXiv records often carry only the abstract page, so the canonical PDF URL is
    derived from the arXiv id when no direct link was stored.
    """
    candidate = paper.get("pdf_url")
    if candidate:
        return candidate

    arxiv_id = (paper.get("source_ids") or {}).get("arxiv")
    if arxiv_id:
        ident = arxiv_id.rsplit("/", 1)[-1]
        return f"https://arxiv.org/pdf/{ident}"

    url = paper.get("url") or ""
    if url.endswith(".pdf"):
        return url
    return None


def safe_filename(paper: dict) -> str:
    title = (paper.get("title") or "paper")[:80]
    year = paper.get("year") or ""
    stem = _UNSAFE_FILENAME.sub("", f"{title} {year}").strip().replace(" ", "_")
    return f"{stem or 'paper'}.pdf"


@router.get("/{paper_id}/file-info", response_model=PaperFileInfoOut)
def paper_file_info(
    paper_id: str,
    repo: PaperRepository = Depends(repo_dep),
) -> PaperFileInfoOut:
    """Whether a PDF can be served, without fetching it.

    The reader asks this before embedding, so an unavailable paper shows an
    explanation instead of an empty frame.
    """
    paper = repo.get(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"paper {paper_id} not found")
    target = resolve_pdf_url(paper)
    return PaperFileInfoOut(
        paper_id=paper_id,
        available=bool(target),
        filename=safe_filename(paper),
        view_url=f"/api/papers/{paper_id}/file",
        download_url=f"/api/papers/{paper_id}/file?download=true",
        external_url=paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else None),
    )


@router.get("/{paper_id}/file")
def stream_paper_file(
    paper_id: str,
    download: bool = Query(False, description="Send as an attachment instead of inline"),
    repo: PaperRepository = Depends(repo_dep),
    settings: Settings = Depends(settings_dep),
) -> StreamingResponse:
    paper = repo.get(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"paper {paper_id} not found")

    target = resolve_pdf_url(paper)
    if not target:
        raise HTTPException(
            status_code=404,
            detail="No PDF is available for this paper. Use the source link instead.",
        )

    parsed = urlparse(target)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Stored PDF location is not a web URL")

    client = httpx.Client(
        timeout=settings.pdf_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent, "Accept": "application/pdf,*/*"},
    )

    try:
        request = client.build_request("GET", target)
        upstream = client.send(request, stream=True)
    except httpx.HTTPError as exc:
        client.close()
        log.warning("pdf fetch failed for %s: %s", paper_id, exc)
        raise HTTPException(status_code=502, detail=f"Could not reach the PDF host: {exc}") from exc

    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        client.close()
        raise HTTPException(status_code=502, detail=f"PDF host returned HTTP {status}")

    content_type = (upstream.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and not content_type.startswith(_PDF_CONTENT_TYPES):
        upstream.close()
        client.close()
        raise HTTPException(
            status_code=415,
            detail=f"Source served {content_type or 'an unknown type'} rather than a PDF",
        )

    declared = upstream.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.pdf_max_bytes:
        upstream.close()
        client.close()
        raise HTTPException(status_code=413, detail="PDF is larger than the configured limit")

    disposition = "attachment" if download else "inline"
    filename = safe_filename(paper)
    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        # The viewer can seek within a cached copy rather than refetching.
        "Cache-Control": "private, max-age=3600",
        "X-Paper-Source": str(paper.get("source") or "unknown"),
    }
    if declared:
        headers["Content-Length"] = declared

    def body():
        sent = 0
        try:
            for chunk in upstream.iter_bytes(64 * 1024):
                sent += len(chunk)
                if sent > settings.pdf_max_bytes:
                    log.warning("pdf for %s exceeded %d bytes, truncated", paper_id, settings.pdf_max_bytes)
                    break
                yield chunk
        finally:
            upstream.close()
            client.close()

    return StreamingResponse(body(), media_type="application/pdf", headers=headers)
