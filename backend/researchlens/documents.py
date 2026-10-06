"""Paper document shape and the pure helpers that build it.

Mongo is schemaless; this module is the single place that decides what a paper
document actually looks like, so every writer agrees.

papers document
---------------
_id             str   - deterministic id derived from the fingerprint
fingerprint     str   - dedupe key: doi > arxiv id > normalized-title hash
title           str
title_slug      str   - normalized title, second-chance dedupe across sources
abstract        str | None
authors         [{name, affiliation?}]
published_date  datetime | None (UTC midnight)
year            int | None
venue           str | None
doi             str | None  (lowercased, bare - no https://doi.org prefix)
url             str | None
pdf_url         str | None
topics          [str]
keywords        [str]
authors_text    str   - flattened for the text index
topics_text     str   - flattened for the text index
full_text       str | None  (Phase 5 / OCR)
citation_count  int
reference_count int
source          str   - "arxiv" | "openalex" | ...
source_ids      {arxiv?, openalex?, doi?, pmid?}
embedding       {model, dim, vector: [float], norm} | absent
created_at      datetime
updated_at      datetime
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_DOI_PREFIX = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.I)
_ARXIV_VERSION = re.compile(r"v\d+$")


@dataclass(slots=True)
class RawPaper:
    """Source-agnostic paper as returned by a PaperSource adapter."""

    title: str
    source: str
    abstract: str | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    published_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    citation_count: int = 0
    reference_count: int = 0
    source_ids: dict[str, str] = field(default_factory=dict)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value)
    value = _WS.sub(" ", value).strip()
    return value or None


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = _DOI_PREFIX.sub("", doi.strip()).strip().lower()
    return doi or None


def normalize_arxiv_id(value: str | None) -> str | None:
    """`http://arxiv.org/abs/2103.00020v1` -> `2103.00020`."""
    if not value:
        return None
    value = value.strip().rsplit("/", 1)[-1]
    value = value.replace("arXiv:", "").replace("arxiv:", "")
    return _ARXIV_VERSION.sub("", value) or None


def title_slug(title: str) -> str:
    """Aggressive normalization used only for fingerprinting near-duplicates."""
    slug = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = _NON_ALNUM.sub(" ", slug.lower())
    return _WS.sub(" ", slug).strip()


def compute_fingerprint(raw: RawPaper) -> str:
    """Stable dedupe key. Strongest available identifier wins.

    The same paper arriving from arXiv and OpenAlex collapses to one document
    whenever either carries a DOI or arXiv id; otherwise the title hash catches
    the common case.
    """
    doi = normalize_doi(raw.doi) or normalize_doi(raw.source_ids.get("doi"))
    if doi:
        return "doi:" + doi
    arxiv_id = normalize_arxiv_id(raw.source_ids.get("arxiv"))
    if arxiv_id:
        return "arxiv:" + arxiv_id
    openalex_id = raw.source_ids.get("openalex")
    slug = title_slug(raw.title)
    if slug:
        return "title:" + hashlib.sha1(slug.encode()).hexdigest()[:32]
    if openalex_id:
        return "openalex:" + openalex_id
    return "unknown:" + hashlib.sha1(repr(raw).encode()).hexdigest()[:32]


def document_id(fingerprint: str) -> str:
    return hashlib.sha1(fingerprint.encode()).hexdigest()[:24]


def _as_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def author_names(authors: list[dict[str, Any]]) -> list[str]:
    return [a.get("name", "") for a in authors if a.get("name")]


def embedding_input(doc: dict[str, Any]) -> str:
    """Text fed to the embedder. Title carries the most signal, so it leads."""
    parts = [doc.get("title") or ""]
    topics = doc.get("topics") or []
    if topics:
        parts.append("Topics: " + ", ".join(topics[:8]))
    if doc.get("abstract"):
        parts.append(doc["abstract"])
    return "\n".join(p for p in parts if p).strip()


def to_document(raw: RawPaper) -> dict[str, Any]:
    """RawPaper -> Mongo document (without timestamps or embedding)."""
    title = clean_text(raw.title) or "(untitled)"
    fingerprint = compute_fingerprint(raw)
    authors = [
        {k: v for k, v in a.items() if v} for a in raw.authors if clean_text(a.get("name"))
    ]
    topics = [t for t in (clean_text(t) for t in raw.topics) if t]
    keywords = [k for k in (clean_text(k) for k in raw.keywords) if k]
    published = _as_datetime(raw.published_date)
    doi = normalize_doi(raw.doi)
    source_ids = {k: v for k, v in raw.source_ids.items() if v}
    if doi:
        source_ids.setdefault("doi", doi)

    return {
        "_id": document_id(fingerprint),
        "fingerprint": fingerprint,
        "title": title,
        "title_slug": title_slug(title),
        "abstract": clean_text(raw.abstract),
        "authors": authors,
        "authors_text": ", ".join(author_names(authors)),
        "published_date": published,
        "year": published.year if published else None,
        "venue": clean_text(raw.venue),
        "doi": doi,
        "url": raw.url,
        "pdf_url": raw.pdf_url,
        "topics": topics,
        "topics_text": ", ".join(topics),
        "keywords": keywords,
        "citation_count": int(raw.citation_count or 0),
        "reference_count": int(raw.reference_count or 0),
        "source": raw.source,
        "source_ids": source_ids,
    }
