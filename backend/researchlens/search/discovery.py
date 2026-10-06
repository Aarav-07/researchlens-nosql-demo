"""Discovery coordinator.

Composes the three pieces that make a query feel like it searched the internet
rather than a local table:

    search (local) -> is coverage thin? -> live fetch -> search again -> group

Keeping this in one place leaves SearchService, LiveFetcher and
RecommendationService each doing exactly one job, and gives the API a single
entry point per user action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings
from ..ingest.service import IngestService
from ..logging_conf import get_logger
from ..repository import PaperRepository
from .live import LiveFetcher
from .recommend import RecommendationService, RecommendationSet, best_local_score
from .service import SearchResponse, SearchService

log = get_logger(__name__)


@dataclass(slots=True)
class DiscoveryResult:
    search: SearchResponse
    live_fetch: dict[str, Any] | None = None
    recommendations: RecommendationSet | None = None
    notes: list[str] = field(default_factory=list)


class DiscoveryService:
    def __init__(
        self,
        repo: PaperRepository | None = None,
        search: SearchService | None = None,
        ingest: IngestService | None = None,
        recommender: RecommendationService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo or PaperRepository()
        self.search_service = search or SearchService(repo=self.repo, settings=self.settings)
        self.ingest_service = ingest or IngestService(repo=self.repo, settings=self.settings)
        self.recommender = recommender or RecommendationService(
            repo=self.repo, settings=self.settings
        )
        self.live = LiveFetcher(self.ingest_service, self.settings)

    def discover(
        self,
        query: str,
        mode: str = "hybrid",
        limit: int = 25,
        live: bool = True,
        recommend: bool = True,
    ) -> DiscoveryResult:
        notes: list[str] = []
        response = self.search_service.search(query, mode=mode, limit=limit)

        live_report: dict[str, Any] | None = None
        if live and query.strip():
            if self.search_service.embedder.is_fallback and response.mode == "keyword":
                similarities = [1.0] * len(response.hits)
            else:
                similarities = [h.similarity for h in response.hits] or [response.top_similarity]
            live_report = self.live.maybe_fetch(query, similarities)
            if live_report:
                notes.append(
                    f"Fetched {live_report['fetched']} papers from "
                    f"{', '.join(s['source'] for s in live_report['sources'] if s['status'] == 'ok')}"
                    f" ({live_report['created']} new)"
                )
                # Re-run against the enlarged corpus.
                response = self.search_service.search(query, mode=mode, limit=limit)

        recommendations = (
            self.recommender.for_query(query, live_fetch=live_report) if recommend else None
        )
        return DiscoveryResult(
            search=response,
            live_fetch=live_report,
            recommendations=recommendations,
            notes=notes,
        )
