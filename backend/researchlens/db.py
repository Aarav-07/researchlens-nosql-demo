"""MongoDB connection + index management.

One process-wide MongoClient (it is thread-safe and pools internally). All
endpoints are sync `def`, so FastAPI runs them in its threadpool and pymongo's
blocking calls stay off the event loop.
"""
from __future__ import annotations

from threading import Lock

from pymongo import ASCENDING, DESCENDING, MongoClient, TEXT
from pymongo.database import Database
from pymongo.errors import OperationFailure, PyMongoError

from .config import Settings, get_settings
from .logging_conf import get_logger

log = get_logger(__name__)

PAPERS = "papers"
SEARCH_LOG = "search_query_log"
INGEST_RUNS = "ingest_runs"

ATLAS_VECTOR_INDEX = "papers_vector_index"
ATLAS_TEXT_INDEX = "papers_text_index"

_client: MongoClient | None = None
_lock = Lock()


def get_client(settings: Settings | None = None) -> MongoClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                s = settings or get_settings()
                _client = MongoClient(
                    s.mongodb_uri,
                    serverSelectionTimeoutMS=s.mongodb_timeout_ms,
                    appname="researchlens",
                    tz_aware=True,
                )
                log.info("MongoClient created for %s", _redact(s.mongodb_uri))
    return _client


def get_db(settings: Settings | None = None) -> Database:
    s = settings or get_settings()
    return get_client(s)[s.mongodb_db]


def close_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
            log.info("MongoClient closed")


def _redact(uri: str) -> str:
    """Strip credentials before anything touches a log line."""
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


def ping(settings: Settings | None = None) -> bool:
    try:
        get_client(settings).admin.command("ping")
        return True
    except PyMongoError as exc:
        log.warning("MongoDB ping failed: %s", exc)
        return False


def is_atlas(settings: Settings | None = None) -> bool:
    """Detect whether $search / $vectorSearch are available.

    Explicit config wins; otherwise probe for the Atlas Search command, which
    community servers do not implement.
    """
    s = settings or get_settings()
    if s.search_backend == "atlas":
        return True
    if s.search_backend == "local":
        return False
    try:
        get_db(s).command({"listSearchIndexes": PAPERS})
        return True
    except OperationFailure:
        return False
    except PyMongoError:
        return False


def ensure_indexes(settings: Settings | None = None) -> dict[str, list[str]]:
    """Idempotent index creation. Safe to call on every startup."""
    s = settings or get_settings()
    db = get_db(s)
    created: dict[str, list[str]] = {PAPERS: [], SEARCH_LOG: [], INGEST_RUNS: []}

    papers = db[PAPERS]
    created[PAPERS].append(papers.create_index([("fingerprint", ASCENDING)], unique=True))
    created[PAPERS].append(papers.create_index([("doi", ASCENDING)], sparse=True))
    created[PAPERS].append(papers.create_index([("title_slug", ASCENDING)]))
    created[PAPERS].append(papers.create_index([("alt_fingerprints", ASCENDING)]))
    created[PAPERS].append(papers.create_index([("source", ASCENDING), ("published_date", DESCENDING)]))
    created[PAPERS].append(papers.create_index([("published_date", DESCENDING)]))
    created[PAPERS].append(papers.create_index([("topics", ASCENDING)]))
    created[PAPERS].append(papers.create_index([("embedding.model", ASCENDING)]))
    created[PAPERS].append(papers.create_index([("citation_count", DESCENDING)]))

    # Community-edition keyword search. Weighted so a title hit outranks an
    # abstract hit. Mongo allows exactly one text index per collection.
    try:
        created[PAPERS].append(
            papers.create_index(
                [("title", TEXT), ("abstract", TEXT), ("authors_text", TEXT), ("topics_text", TEXT)],
                name="papers_fulltext",
                weights={"title": 10, "topics_text": 5, "authors_text": 3, "abstract": 1},
                default_language="english",
            )
        )
    except OperationFailure as exc:
        # Already exists with different options - keep the existing one.
        log.warning("text index not recreated: %s", exc)

    created[SEARCH_LOG].append(db[SEARCH_LOG].create_index([("created_at", DESCENDING)]))
    created[INGEST_RUNS].append(db[INGEST_RUNS].create_index([("created_at", DESCENDING)]))

    log.info("indexes ensured: %s", {k: len(v) for k, v in created.items()})
    return created


def ensure_atlas_search_indexes(dim: int, settings: Settings | None = None) -> list[str]:
    """Create Atlas Search + Vector Search indexes when running on Atlas.

    No-op (and never fatal) on community servers.
    """
    s = settings or get_settings()
    if not is_atlas(s):
        return []
    db = get_db(s)
    wanted = [
        {
            "name": ATLAS_VECTOR_INDEX,
            "type": "vectorSearch",
            "definition": {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding.vector",
                        "numDimensions": dim,
                        "similarity": "cosine",
                    },
                    {"type": "filter", "path": "source"},
                ]
            },
        },
        {
            "name": ATLAS_TEXT_INDEX,
            "type": "search",
            "definition": {"mappings": {"dynamic": True}},
        },
    ]
    made: list[str] = []
    try:
        existing = {i["name"] for i in db[PAPERS].list_search_indexes()}
    except PyMongoError as exc:
        log.warning("could not list Atlas search indexes: %s", exc)
        return []
    for spec in wanted:
        if spec["name"] in existing:
            continue
        try:
            db[PAPERS].create_search_index(spec)
            made.append(spec["name"])
            log.info("Atlas search index requested: %s", spec["name"])
        except PyMongoError as exc:
            log.warning("Atlas index %s failed: %s", spec["name"], exc)
    return made
