"""Maintenance commands.

    python scripts/maintenance.py dedupe    # merge records that share a title
    python scripts/maintenance.py embed     # embed anything missing a vector
    python scripts/maintenance.py reembed   # rebuild every vector with the active model
    python scripts/maintenance.py stats     # print corpus counters

`dedupe` exists because dedupe rules improve over time; records collected under
an older rule need a way to be folded together without re-ingesting everything.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from researchlens.db import PAPERS, ensure_indexes, get_db  # noqa: E402
from researchlens.logging_conf import configure_logging, get_logger  # noqa: E402
from researchlens.repository import _fingerprint_rank, _merge  # noqa: E402

log = get_logger("researchlens.maintenance")

SKIP_FIELDS = {"_id", "fingerprint", "alt_fingerprints", "created_at", "updated_at", "embedding"}


def dedupe() -> int:
    """Fold documents that share a normalized title into one record."""
    db = get_db()
    col = db[PAPERS]
    groups = col.aggregate(
        [
            {"$match": {"title_slug": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$title_slug", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
        ]
    )

    merged = 0
    for group in groups:
        docs = list(col.find({"_id": {"$in": group["ids"]}}))
        docs.sort(key=lambda d: (_fingerprint_rank(d.get("fingerprint", "")), d.get("created_at")))
        winner, losers = docs[0], docs[1:]

        payload = dict(winner)
        alts = set(winner.get("alt_fingerprints") or [])
        for loser in losers:
            payload = _merge(payload, {k: v for k, v in loser.items() if k not in SKIP_FIELDS})
            if loser.get("fingerprint"):
                alts.add(loser["fingerprint"])
            alts.update(loser.get("alt_fingerprints") or [])
        alts.discard(winner.get("fingerprint"))

        update = {k: v for k, v in payload.items() if k not in SKIP_FIELDS}
        if alts:
            update["alt_fingerprints"] = sorted(alts)
        col.update_one({"_id": winner["_id"]}, {"$set": update})
        col.delete_many({"_id": {"$in": [d["_id"] for d in losers]}})
        merged += len(losers)
        log.info("merged %d duplicate(s) into %s", len(losers), winner["_id"])

    log.info("dedupe complete: %d documents removed", merged)
    return merged


def embed() -> int:
    from researchlens.ingest.service import IngestService

    count = IngestService().backfill_embeddings()
    log.info("embedded %d papers", count)
    return count


def reembed() -> int:
    """Re-embed every paper with the currently loaded model.

    Use after a model change, or to repair a corpus that was written in the
    fallback vector space.
    """
    from researchlens.ingest.service import IngestService

    service = IngestService()
    if service.embedder.is_fallback:
        log.error(
            "the fallback embedder is active; refusing to rewrite the corpus with it. "
            "Fix the model load first."
        )
        return 0

    db = get_db()
    result = db[PAPERS].update_many(
        {"embedding.model": {"$ne": service.embedder.name}}, {"$unset": {"embedding": ""}}
    )
    log.info("cleared %d stale vectors", result.modified_count)
    count = service.backfill_embeddings(force=True)
    log.info("re-embedded %d papers with %s", count, service.embedder.name)
    return count


def stats() -> None:
    from researchlens.repository import PaperRepository

    print(PaperRepository().stats())


COMMANDS = {"dedupe": dedupe, "embed": embed, "reembed": reembed, "stats": stats}


def main() -> int:
    configure_logging("INFO")
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: python scripts/maintenance.py [{' | '.join(COMMANDS)}]")
        return 2
    ensure_indexes()
    COMMANDS[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
