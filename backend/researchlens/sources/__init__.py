"""Source registry. One entry per provider - the only place to add a new one."""
from __future__ import annotations

from ..config import Settings, get_settings
from .arxiv import ArxivSource
from .base import PaperSource, SourceError
from .openalex import OpenAlexSource

_REGISTRY: dict[str, type[PaperSource]] = {
    ArxivSource.name: ArxivSource,
    OpenAlexSource.name: OpenAlexSource,
}

DEFAULT_SOURCES: tuple[str, ...] = (ArxivSource.name, OpenAlexSource.name)


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


def get_source(name: str, settings: Settings | None = None) -> PaperSource:
    try:
        cls = _REGISTRY[name.lower()]
    except KeyError as exc:
        raise SourceError(name, f"unknown source (have: {', '.join(available_sources())})") from exc
    return cls(settings or get_settings())


__all__ = [
    "ArxivSource",
    "OpenAlexSource",
    "PaperSource",
    "SourceError",
    "DEFAULT_SOURCES",
    "available_sources",
    "get_source",
]
