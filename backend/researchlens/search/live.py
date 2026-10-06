"""Live coverage: fetch from the internet at search time when the local corpus
cannot answer a query well.

Why this exists: a static corpus is the reason existing tools go stale (new
papers take weeks to show up) and the reason a fresh install returns nothing.
Instead of pre-crawling everything, a query that the corpus answers poorly
triggers a bounded fetch from the sources, embeds the results, and re-runs the
search against the enlarged corpus.

Guards, so this never turns into a fetch on every keystroke:
* a query whose local answer is already good enough skips the fetch entirely;
* the same normalized query is not re-fetched within `live_cooldown_hours`;
* only `live_limit_per_source` records per source per fetch.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..db import get_db
from ..logging_conf import get_logger

log = get_logger(__name__)

LIVE_QUERIES = "live_queries"
_WS = re.compile(r"\s+")
# Serializes identical concurrent queries so two users typing the same thing do
# not both trigger the same fetch.
_locks: dict[str, Lock] = {}
_locks_guard = Lock()


def normalize_query(query: str) -> str:
    return _WS.sub(" ", query.strip().lower())


def _lock_for(key: str) -> Lock:
    with _locks_guard:
        return _locks.setdefault(key, Lock())


def recently_fetched(query: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=s.live_cooldown_hours)
    doc = get_db(s)[LIVE_QUERIES].find_one(
        {"_id": normalize_query(query), "fetched_at": {"$gte": cutoff}}
    )
    return doc is not None


def mark_fetched(query: str, report: dict[str, Any], settings: Settings | None = None) -> None:
    s = settings or get_settings()
    get_db(s)[LIVE_QUERIES].update_one(
        {"_id": normalize_query(query)},
        {
            "$set": {
                "fetched_at": datetime.now(timezone.utc),
                "fetched": report.get("fetched", 0),
                "created": report.get("created", 0),
            },
            "$inc": {"fetch_count": 1},
        },
        upsert=True,
    )


def coverage_is_thin(
    similarities: Sequence[float], settings: Settings | None = None
) -> bool:
    """Decide whether the local corpus answered well enough.

    Depth matters, not just the single best hit. A corpus collected for one
    narrow topic will always have *something* adjacent to a neighbouring query:
    asking "photovoltaic cells" of a corpus full of solar-panel-waste papers
    returns a best match around 0.49, which passes a top-score test while every
    result is still the wrong literature. So a topic counts as covered only when
    enough papers are genuinely close to it.
    """
    s = settings or get_settings()
    if not similarities:
        return True
    top = max(similarities)
    good = sum(1 for value in similarities if value >= s.live_good_similarity)
    return top < s.live_min_top_score or good < s.live_min_results


class LiveFetcher:
    """Wraps IngestService with the cooldown and locking policy above."""

    def __init__(self, ingest_service, settings: Settings | None = None) -> None:
        self.ingest = ingest_service
        self.settings = settings or get_settings()

    def maybe_fetch(self, query: str, similarities: Sequence[float]) -> dict[str, Any] | None:
        """Returns the ingest report when a fetch happened, else None."""
        s = self.settings
        if not s.live_search_enabled:
            return None
        if not coverage_is_thin(similarities, s):
            return None
        if recently_fetched(query, s):
            log.info("live fetch skipped (cooldown): %r", query)
            return None

        with _lock_for(normalize_query(query)):
            # Re-check inside the lock: another request may have just fetched.
            if recently_fetched(query, s):
                return None
            good = sum(1 for v in similarities if v >= s.live_good_similarity)
            log.info(
                "live fetch for %r (best=%.3f, %d good local matches)",
                query,
                max(similarities, default=0.0),
                good,
            )
            report = self.ingest.ingest_query(
                query=query,
                limit_per_source=s.live_limit_per_source,
                sort="relevance",
                embed=True,
            )
            payload = report.as_dict()
            mark_fetched(query, payload, s)
            return payload
