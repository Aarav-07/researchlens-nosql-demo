"""Pydantic request/response models - the API contract.

Mongo documents use `_id`; the wire format uses `id`. That translation happens
here and nowhere else.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Author(BaseModel):
    name: str
    affiliation: str | None = None


class PaperOut(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    published_date: date | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    citation_count: int = 0
    source: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    has_embedding: bool = False

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "PaperOut":
        published = doc.get("published_date")
        if isinstance(published, datetime):
            published = published.date()
        return cls(
            id=doc["_id"],
            title=doc.get("title", ""),
            abstract=doc.get("abstract"),
            authors=[Author(**a) for a in (doc.get("authors") or [])],
            published_date=published,
            year=doc.get("year"),
            venue=doc.get("venue"),
            doi=doc.get("doi"),
            url=doc.get("url"),
            pdf_url=doc.get("pdf_url"),
            topics=doc.get("topics") or [],
            keywords=doc.get("keywords") or [],
            citation_count=int(doc.get("citation_count") or 0),
            source=doc.get("source", "unknown"),
            source_ids={k: str(v) for k, v in (doc.get("source_ids") or {}).items()},
            has_embedding=bool((doc.get("embedding") or {}).get("model")),
        )


class PaperListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PaperOut]


class SearchHitOut(BaseModel):
    paper: PaperOut
    score: float
    score_parts: dict[str, float] = Field(default_factory=dict)
    reason: str = ""
    # Raw cosine against the query. Unlike `score`, this is comparable across
    # searches, so the UI can say how good a match really is.
    similarity: float = 0.0


class SearchResponseOut(BaseModel):
    query: str
    mode: str
    total: int
    took_ms: int
    backend: str
    top_similarity: float = 0.0
    hits: list[SearchHitOut]


class LiveFetchOut(BaseModel):
    fetched: int
    created: int
    updated: int
    embedded: int
    sources: list["SourceOutcomeOut"] = Field(default_factory=list)


class RecommendationGroupOut(BaseModel):
    key: str
    title: str
    description: str
    hits: list[SearchHitOut]


class RecommendationsOut(BaseModel):
    query: str
    took_ms: int
    considered: int
    groups: list[RecommendationGroupOut]


class DiscoverOut(BaseModel):
    """Search results plus grouped recommendations, plus what was fetched live."""

    search: SearchResponseOut
    recommendations: RecommendationsOut | None = None
    live_fetch: LiveFetchOut | None = None
    notes: list[str] = Field(default_factory=list)


class PaperFileInfoOut(BaseModel):
    paper_id: str
    available: bool
    filename: str
    view_url: str
    download_url: str
    external_url: str | None = None


class IngestRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    sources: list[str] | None = None
    limit_per_source: int = Field(default=25, ge=1, le=200)
    sort: Literal["relevance", "date", "citations", "updated"] = "relevance"
    embed: bool = True

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query cannot be blank")
        return v


class SourceOutcomeOut(BaseModel):
    source: str
    fetched: int = 0
    status: str = "ok"
    error: str | None = None


class IngestResponseOut(BaseModel):
    query: str
    requested: int
    fetched: int
    created: int
    updated: int
    embedded: int
    sources: list[SourceOutcomeOut]


class EmbedRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100_000)


class EmbedResponseOut(BaseModel):
    embedded: int
    model: str
    dim: int
    index_backend: str
    indexed_vectors: int


class TopicCount(BaseModel):
    topic: str
    count: int


class HealthOut(BaseModel):
    status: str
    mongodb: bool
    search_backend: str
    embedding_model: str
    embedding_dim: int
    papers: int
    embedded: int
    # True when running on the degraded hashing embedder, or when the corpus is
    # mostly embedded with a different model than the one now loaded.
    embedding_degraded: bool = False
    corpus_embedding_model: str | None = None


class StatsOut(BaseModel):
    papers: int
    embedded: int
    by_source: dict[str, int]
    top_topics: list[TopicCount]
    embedding_model: str
    search_backend: str
    index_backend: str
    indexed_vectors: int
