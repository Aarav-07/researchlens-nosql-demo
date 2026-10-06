"""Source adapter contract.

A source knows how to turn a natural-language query into `RawPaper` objects. It
does no storage, no dedupe, no embedding - that is the ingest service's job.
Adding a new provider (Crossref, Semantic Scholar, PubMed) means one new module
implementing `PaperSource` plus one line in the registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

import httpx

from ..config import Settings, get_settings
from ..documents import RawPaper
from ..logging_conf import get_logger

log = get_logger(__name__)


class SourceError(RuntimeError):
    """Upstream provider failed. Carries the source name for the API layer."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message


class PaperSource(ABC):
    name: str
    supports_full_text: bool = False

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @abstractmethod
    def search(self, query: str, limit: int = 25, **kwargs) -> list[RawPaper]:
        """Fetch up to `limit` papers matching `query`."""

    def fetch_by_id(self, external_id: str) -> RawPaper | None:
        """Optional: single-record lookup by the provider's own id."""
        return None

    # ------------------------------------------------------------------ helpers

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        try:
            with self._client() as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            raise SourceError(self.name, f"HTTP {exc.response.status_code} from {url}") from exc
        except httpx.HTTPError as exc:
            raise SourceError(self.name, f"request failed: {exc}") from exc

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        """Accepts YYYY, YYYY-MM, YYYY-MM-DD and ISO timestamps."""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        head = text[:10]
        for fmt, width in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
            try:
                return datetime.strptime(head[:width], fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            log.debug("unparsable date %r", value)
            return None
