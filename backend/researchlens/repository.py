"""Data access for papers. Every Mongo query the app issues lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from pymongo import DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError
from pymongo.database import Database

from . import db as dbmod
from .documents import RawPaper, to_document
from .logging_conf import get_logger

log = get_logger(__name__)

# Fields returned to clients by default - full_text and raw vectors stay out.
LIST_PROJECTION: dict[str, int] = {
    "title": 1,
    "abstract": 1,
    "authors": 1,
    "published_date": 1,
    "year": 1,
    "venue": 1,
    "doi": 1,
    "url": 1,
    "pdf_url": 1,
    "topics": 1,
    "keywords": 1,
    "citation_count": 1,
    "source": 1,
    "source_ids": 1,
    "embedding.model": 1,
}

_EMPTY = (None, [], "", {})


@dataclass(slots=True)
class UpsertResult:
    created: int = 0
    updated: int = 0
    ids: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaperRepository:
    def __init__(self, database: Database | None = None) -> None:
        # pymongo Database forbids truth testing, so the None check is explicit.
        self.db = database if database is not None else dbmod.get_db()
        self.col = self.db[dbmod.PAPERS]

    # ------------------------------------------------------------------ writes

    def upsert_many(self, raws: Iterable[RawPaper]) -> UpsertResult:
        """Insert new papers, enrich existing ones. Never overwrites with empty.

        Dedupe is two-tier: the `fingerprint` (DOI > arXiv id > title hash) is the
        primary key, and the normalized title catches the same work arriving under
        two different identifiers (arXiv preprint vs. published DOI).

        `fingerprint` is written once, at insert. When an incoming record merges
        into an existing document under a *different* fingerprint, the incoming one
        is appended to `alt_fingerprints` instead of replacing the stored value -
        overwriting it would collide with the unique index the moment the other
        variant is ingested again.
        """
        docs = [to_document(r) for r in raws]
        if not docs:
            return UpsertResult()

        # Collapse duplicates inside this batch: first by fingerprint, then by
        # title. The second pass matters because arXiv and OpenAlex return the
        # same paper under different identifiers in the *same* fetch, so neither
        # record is in the database yet for the title lookup below to catch.
        by_fp: dict[str, dict[str, Any]] = {}
        for doc in docs:
            existing = by_fp.get(doc["fingerprint"])
            by_fp[doc["fingerprint"]] = _merge(existing, doc) if existing else doc

        by_slug: dict[str, dict[str, Any]] = {}
        collapsed: list[dict[str, Any]] = []
        for doc in by_fp.values():
            slug = doc.get("title_slug") or ""
            if not slug:
                collapsed.append(doc)
                continue
            twin = by_slug.get(slug)
            if twin is None:
                by_slug[slug] = doc
                collapsed.append(doc)
                continue
            # Keep the stronger identifier, merge the rest of the fields into it.
            winner, loser = (
                (doc, twin) if _fingerprint_rank(doc["fingerprint"]) < _fingerprint_rank(twin["fingerprint"]) else (twin, doc)
            )
            merged = _merge(winner, loser)
            merged["fingerprint"] = winner["fingerprint"]
            merged["_id"] = winner["_id"]
            # Keep the discarded identifier so the same record arriving under it
            # later resolves to this document instead of creating a new one.
            merged["alt_fingerprints"] = sorted(
                set(winner.get("alt_fingerprints") or [])
                | set(loser.get("alt_fingerprints") or [])
                | {loser["fingerprint"]}
            )
            by_slug[slug] = merged
            collapsed[collapsed.index(twin)] = merged

        existing_by_fp, existing_by_slug = self._lookup_existing(collapsed)

        ops: list[UpdateOne] = []
        ids: list[str] = []
        now = _utcnow()
        for doc in collapsed:
            doc = dict(doc)
            fingerprint = doc.pop("fingerprint")
            slug = doc.get("title_slug") or ""
            # A fingerprint hit is authoritative; a title hit is the fallback.
            match = existing_by_fp.get(fingerprint) or existing_by_slug.get(slug)
            target_id = match["_id"] if match else doc["_id"]
            doc["_id"] = target_id
            ids.append(target_id)

            set_fields = {k: v for k, v in doc.items() if k != "_id" and v not in _EMPTY}
            # citation_count is applied via $max below, so keep it out of $set.
            citations = int(set_fields.pop("citation_count", 0) or 0)
            # alt_fingerprints is an $addToSet field; $set on it would conflict.
            alts = set(set_fields.pop("alt_fingerprints", []) or [])
            set_fields["updated_at"] = now

            if match and match.get("fingerprint") != fingerprint:
                alts.add(fingerprint)
            alts.discard(match.get("fingerprint") if match else fingerprint)

            update: dict[str, Any] = {
                "$set": set_fields,
                "$setOnInsert": {"created_at": now, "fingerprint": fingerprint},
                # Sources disagree and lag; highest count seen wins.
                "$max": {"citation_count": citations},
            }
            if alts:
                update["$addToSet"] = {"alt_fingerprints": {"$each": sorted(alts)}}

            ops.append(UpdateOne({"_id": target_id}, update, upsert=True))

        created, updated = self._write(ops)
        log.info("upsert: %d created, %d updated (%d submitted)", created, updated, len(ops))
        return UpsertResult(created=created, updated=updated, ids=ids)

    def _lookup_existing(
        self, docs: Sequence[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """One query resolving both dedupe tiers for the whole batch."""
        fingerprints = [d["fingerprint"] for d in docs]
        slugs = [d["title_slug"] for d in docs if d.get("title_slug")]
        if not fingerprints and not slugs:
            return {}, {}
        cursor = self.col.find(
            {
                "$or": [
                    {"fingerprint": {"$in": fingerprints}},
                    {"alt_fingerprints": {"$in": fingerprints}},
                    {"title_slug": {"$in": slugs}},
                ]
            },
            {"fingerprint": 1, "alt_fingerprints": 1, "title_slug": 1},
        )
        by_fp: dict[str, dict[str, Any]] = {}
        by_slug: dict[str, dict[str, Any]] = {}
        for hit in cursor:
            if hit.get("fingerprint"):
                by_fp[hit["fingerprint"]] = hit
            for alt in hit.get("alt_fingerprints") or []:
                by_fp.setdefault(alt, hit)
            if hit.get("title_slug"):
                by_slug.setdefault(hit["title_slug"], hit)
        return by_fp, by_slug

    def _write(self, ops: list[UpdateOne]) -> tuple[int, int]:
        """Bulk write that survives duplicate-key races on `fingerprint`.

        Two ingests touching the same new paper concurrently can both try to
        insert it. The loser's rows are reported here rather than failing the run.
        """
        if not ops:
            return 0, 0
        try:
            res = self.col.bulk_write(ops, ordered=False)
            return res.upserted_count, res.modified_count
        except BulkWriteError as exc:
            details = exc.details or {}
            dup = [e for e in details.get("writeErrors", []) if e.get("code") == 11000]
            other = [e for e in details.get("writeErrors", []) if e.get("code") != 11000]
            if other:
                raise
            log.warning("upsert: %d duplicate-key rows skipped", len(dup))
            return int(details.get("nUpserted", 0)), int(details.get("nModified", 0))

    def set_embeddings_bulk(
        self, rows: Sequence[tuple[str, str, int, Sequence[float], float]]
    ) -> int:
        """rows: (paper_id, model, dim, vector, norm)."""
        if not rows:
            return 0
        now = _utcnow()
        ops = [
            UpdateOne(
                {"_id": pid},
                {
                    "$set": {
                        "embedding": {
                            "model": model,
                            "dim": dim,
                            "vector": [float(v) for v in vec],
                            "norm": float(norm),
                            "created_at": now,
                        },
                        "updated_at": now,
                    }
                },
            )
            for pid, model, dim, vec, norm in rows
        ]
        res = self.col.bulk_write(ops, ordered=False)
        return res.modified_count

    def set_full_text(self, paper_id: str, text: str) -> None:
        """Phase 5 / OCR hook - stored but not yet embedded."""
        self.col.update_one(
            {"_id": paper_id}, {"$set": {"full_text": text, "updated_at": _utcnow()}}
        )

    # ------------------------------------------------------------------- reads

    def get(self, paper_id: str, include_full_text: bool = False) -> dict[str, Any] | None:
        projection = dict(LIST_PROJECTION)
        if include_full_text:
            projection["full_text"] = 1
        return self.col.find_one({"_id": paper_id}, projection)

    def get_many(self, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        cursor = self.col.find({"_id": {"$in": list(ids)}}, LIST_PROJECTION)
        return {d["_id"]: d for d in cursor}

    def get_vector(self, paper_id: str) -> dict[str, Any] | None:
        doc = self.col.find_one({"_id": paper_id}, {"embedding": 1})
        return (doc or {}).get("embedding")

    def list_papers(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        topic: str | None = None,
        sort: str = "date",
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {}
        if source:
            query["source"] = source
        if topic:
            query["topics"] = topic
        sort_key = {
            "date": "published_date",
            "citations": "citation_count",
            "added": "created_at",
        }.get(sort, "published_date")
        total = self.col.count_documents(query)
        cursor = (
            self.col.find(query, LIST_PROJECTION)
            .sort([(sort_key, DESCENDING)])
            .skip(max(offset, 0))
            .limit(limit)
        )
        return list(cursor), total

    def text_search(self, query: str, limit: int) -> list[tuple[str, float, dict[str, Any]]]:
        """Community-edition keyword search via the weighted text index."""
        projection = dict(LIST_PROJECTION)
        projection["score"] = {"$meta": "textScore"}  # type: ignore[assignment]
        cursor = (
            self.col.find({"$text": {"$search": query}}, projection)
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        return [(d["_id"], float(d.pop("score", 0.0)), d) for d in cursor]

    def atlas_text_search(self, query: str, limit: int) -> list[tuple[str, float, dict[str, Any]]]:
        """Atlas Search ($search) keyword path - richer scoring than $text."""
        pipeline = [
            {
                "$search": {
                    "index": dbmod.ATLAS_TEXT_INDEX,
                    "text": {
                        "query": query,
                        "path": ["title", "abstract", "authors_text", "topics_text"],
                    },
                }
            },
            {"$limit": limit},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$project": {**LIST_PROJECTION, "score": 1}},
        ]
        return [(d["_id"], float(d.get("score", 0.0)), d) for d in self.col.aggregate(pipeline)]

    def atlas_vector_search(
        self, vector: Sequence[float], limit: int, candidates: int
    ) -> list[tuple[str, float, dict[str, Any]]]:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": dbmod.ATLAS_VECTOR_INDEX,
                    "path": "embedding.vector",
                    "queryVector": [float(v) for v in vector],
                    "numCandidates": candidates,
                    "limit": limit,
                }
            },
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {"$project": {**LIST_PROJECTION, "score": 1}},
        ]
        return [(d["_id"], float(d.get("score", 0.0)), d) for d in self.col.aggregate(pipeline)]

    def iter_embeddings(self, model: str, batch_size: int = 500) -> Iterator[dict[str, Any]]:
        """Stream stored vectors - used to build the in-process vector index."""
        cursor = self.col.find(
            {"embedding.model": model},
            {"embedding.vector": 1, "embedding.norm": 1},
            batch_size=batch_size,
        )
        yield from cursor

    def iter_needing_embedding(
        self, model: str, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        query = {
            "$or": [
                {"embedding": {"$exists": False}},
                {"embedding.model": {"$ne": model}},
            ]
        }
        cursor = self.col.find(query, {"title": 1, "abstract": 1, "topics": 1})
        if limit:
            cursor = cursor.limit(limit)
        yield from cursor

    def count(self, query: dict[str, Any] | None = None) -> int:
        return self.col.count_documents(query or {})

    def dominant_embedding_model(self) -> str | None:
        """The model most of the corpus is embedded with, if any."""
        rows = list(
            self.col.aggregate(
                [
                    {"$match": {"embedding.model": {"$exists": True}}},
                    {"$group": {"_id": "$embedding.model", "n": {"$sum": 1}}},
                    {"$sort": {"n": DESCENDING}},
                    {"$limit": 1},
                ]
            )
        )
        return rows[0]["_id"] if rows else None

    def distinct_topics(self, limit: int = 40) -> list[dict[str, Any]]:
        pipeline = [
            {"$unwind": "$topics"},
            {"$group": {"_id": "$topics", "count": {"$sum": 1}}},
            {"$sort": {"count": DESCENDING}},
            {"$limit": limit},
        ]
        return [{"topic": d["_id"], "count": d["count"]} for d in self.col.aggregate(pipeline)]

    def stats(self, model: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "papers": self.count(),
            "by_source": {
                d["_id"]: d["count"]
                for d in self.col.aggregate(
                    [
                        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ]
                )
            },
        }
        out["embedded"] = (
            self.count({"embedding.model": model})
            if model
            else self.count({"embedding": {"$exists": True}})
        )
        return out


def _fingerprint_rank(fingerprint: str) -> int:
    """Lower is stronger: a DOI beats an arXiv id, which beats a title hash."""
    if fingerprint.startswith("doi:"):
        return 0
    if fingerprint.startswith("arxiv:"):
        return 1
    return 2


def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Field-wise merge preferring non-empty values; longer abstract wins."""
    out = dict(base)
    for key, value in incoming.items():
        if value in _EMPTY or value == 0:
            continue
        current = out.get(key)
        if current in _EMPTY or current == 0:
            out[key] = value
        elif key == "abstract" and len(str(value)) > len(str(current)):
            out[key] = value
        elif key == "citation_count":
            out[key] = max(int(current), int(value))
        elif key in ("topics", "keywords"):
            out[key] = list(dict.fromkeys(list(current) + list(value)))
    return out
