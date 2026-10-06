"""FastAPI dependencies. Wiring only - no logic."""
from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from ..ingest.service import IngestService
from ..repository import PaperRepository
from ..search.discovery import DiscoveryService
from ..search.recommend import RecommendationService
from ..search.service import SearchService


def settings_dep() -> Settings:
    return get_settings()


@lru_cache
def _repo() -> PaperRepository:
    return PaperRepository()


@lru_cache
def _search() -> SearchService:
    return SearchService(repo=_repo())


@lru_cache
def _ingest() -> IngestService:
    return IngestService(repo=_repo())


@lru_cache
def _recommender() -> RecommendationService:
    return RecommendationService(repo=_repo())


@lru_cache
def _discovery() -> DiscoveryService:
    return DiscoveryService(
        repo=_repo(),
        search=_search(),
        ingest=_ingest(),
        recommender=_recommender(),
    )


def repo_dep() -> PaperRepository:
    return _repo()


def search_dep() -> SearchService:
    return _search()


def ingest_dep() -> IngestService:
    return _ingest()


def recommender_dep() -> RecommendationService:
    return _recommender()


def discovery_dep() -> DiscoveryService:
    return _discovery()


def reset_dependencies() -> None:
    """Test hook - clears cached singletons."""
    _repo.cache_clear()
    _search.cache_clear()
    _ingest.cache_clear()
    _recommender.cache_clear()
    _discovery.cache_clear()
