"""Ingest orchestration: fetch from sources -> dedupe/upsert -> embed.

This is the only component that writes papers. Sources stay dumb (fetch + map),
the repository stays dumb (persist), and the embedding backfill is idempotent so
a crashed run is fixed by re-running it.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..db import INGEST_RUNS, get_db
from ..documents import RawPaper, embedding_input
from ..logging_conf import get_logger
from ..ml.embeddings import Embedder, get_embedder
from ..ml.vector_index import invalidate_vector_index
from ..repository import PaperRepository
from ..sources import DEFAULT_SOURCES, SourceError, get_source

log = get_logger(__name__)


@dataclass(slots=True)
class SourceOutcome:
    source: str
    fetched: int = 0
    status: str = "ok"
    error: str | None = None


@dataclass(slots=True)
class IngestReport:
    query: str
    requested: int
    fetched: int = 0
    created: int = 0
    updated: int = 0
    embedded: int = 0
    sources: list[SourceOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = [asdict(s) for s in self.sources]
        return data


class IngestService:
    def __init__(
        self,
        repo: PaperRepository | None = None,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo or PaperRepository()
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        # Lazy so importing the service never loads a model.
        if self._embedder is None:
            self._embedder = get_embedder(self.settings)
        return self._embedder

    # ------------------------------------------------------------------ ingest

    def ingest_query(
        self,
        query: str,
        sources: Sequence[str] | None = None,
        limit_per_source: int = 25,
        sort: str = "relevance",
        embed: bool = True,
    ) -> IngestReport:
        """Fetch `query` from every requested source, store, then embed.

        One failing source does not sink the run: it is recorded in the report and
        the others still land.
        """
        source_names = list(sources or DEFAULT_SOURCES)
        report = IngestReport(query=query, requested=limit_per_source * len(source_names))

        raws: list[RawPaper] = []
        # Providers are independent and IO-bound - fetch them concurrently.
        with ThreadPoolExecutor(max_workers=max(1, len(source_names))) as pool:
            futures = {
                pool.submit(self._fetch_one, name, query, limit_per_source, sort): name
                for name in source_names
            }
            for future, name in futures.items():
                outcome, papers = future.result()
                report.sources.append(outcome)
                raws.extend(papers)

        report.fetched = len(raws)
        if raws:
            result = self.repo.upsert_many(raws)
            report.created = result.created
            report.updated = result.updated

        if embed:
            report.embedded = self.backfill_embeddings()

        self._record_run(report)
        log.info(
            "ingest %r: fetched=%d created=%d updated=%d embedded=%d",
            query,
            report.fetched,
            report.created,
            report.updated,
            report.embedded,
        )
        return report

    def _fetch_one(
        self, name: str, query: str, limit: int, sort: str
    ) -> tuple[SourceOutcome, list[RawPaper]]:
        try:
            source = get_source(name, self.settings)
            papers = source.search(query, limit=limit, sort=sort)
            return SourceOutcome(source=name, fetched=len(papers)), papers
        except SourceError as exc:
            log.warning("source %s failed: %s", name, exc.message)
            return SourceOutcome(source=name, status="error", error=exc.message), []
        except Exception as exc:  # defensive: a bad payload must not kill ingest
            log.exception("source %s crashed", name)
            return SourceOutcome(source=name, status="error", error=str(exc)), []

    # -------------------------------------------------------------- embeddings

    def backfill_embeddings(
        self,
        batch_size: int | None = None,
        limit: int | None = None,
        force: bool = False,
    ) -> int:
        """Embed every paper missing a vector for the active model. Idempotent.

        Guard: when the active embedder is the degraded fallback and the corpus
        already holds vectors from a real model, this refuses to touch them.
        A transient load failure would otherwise rewrite the whole corpus in a
        weaker vector space, which is not recoverable without re-embedding
        everything. Pass force=True to deliberately migrate models.
        """
        model = self.embedder.name
        dim = self.embedder.dim

        if self.embedder.is_fallback and not force:
            existing = self.repo.dominant_embedding_model()
            if existing and existing != model:
                log.error(
                    "refusing to re-embed %d papers from %r into fallback space %r; "
                    "fix the embedding model and restart",
                    self.repo.count({"embedding.model": existing}),
                    existing,
                    model,
                )
                return 0
        batch_size = batch_size or self.settings.embedding_batch_size
        total = 0
        batch: list[dict[str, Any]] = []

        for doc in self.repo.iter_needing_embedding(model, limit=limit):
            batch.append(doc)
            if len(batch) >= batch_size:
                total += self._embed_batch(batch, model, dim)
                batch = []
        if batch:
            total += self._embed_batch(batch, model, dim)

        if total:
            invalidate_vector_index()
            log.info("embedded %d papers with %s", total, model)
        return total

    def _embed_batch(self, docs: list[dict[str, Any]], model: str, dim: int) -> int:
        texts = [embedding_input(d) for d in docs]
        vectors = self.embedder.encode(texts)
        rows = [
            (doc["_id"], model, dim, vectors[i].tolist(), 1.0)  # encoders return unit-norm rows
            for i, doc in enumerate(docs)
        ]
        return self.repo.set_embeddings_bulk(rows)

    # ------------------------------------------------------------------- audit

    def _record_run(self, report: IngestReport) -> None:
        try:
            get_db(self.settings)[INGEST_RUNS].insert_one(
                {
                    **report.as_dict(),
                    "model": self.embedder.name if report.embedded else None,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        except Exception:  # audit trail must never break the request
            log.exception("failed to record ingest run")
