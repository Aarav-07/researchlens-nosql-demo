"""Vector similarity search.

Two backends behind one interface:

* `LocalVectorIndex`  - loads all stored vectors into one numpy matrix and does
  brute-force cosine (a dot product, since vectors are stored unit-norm). Exact,
  zero extra infrastructure, comfortable to ~100k papers on a laptop.
* `AtlasVectorIndex`  - delegates to MongoDB Atlas `$vectorSearch` (HNSW).

`get_vector_index()` picks by capability: Atlas when available, local otherwise.
Swapping in FAISS later means adding one more class here and nothing else.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import Any, Sequence

import numpy as np

from ..config import Settings, get_settings
from ..db import is_atlas
from ..logging_conf import get_logger
from ..repository import PaperRepository

log = get_logger(__name__)


class VectorIndex(ABC):
    backend: str

    @abstractmethod
    def search(self, vector: np.ndarray, limit: int) -> list[tuple[str, float]]:
        """Returns [(paper_id, cosine_similarity)] sorted best-first."""

    @abstractmethod
    def size(self) -> int: ...

    def invalidate(self) -> None:
        """Called after writes. No-op for server-side indexes."""


class AtlasVectorIndex(VectorIndex):
    backend = "atlas"

    def __init__(self, repo: PaperRepository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings

    def search(self, vector: np.ndarray, limit: int) -> list[tuple[str, float]]:
        hits = self._repo.atlas_vector_search(
            vector.tolist(), limit=limit, candidates=self._settings.vector_candidate_pool
        )
        return [(pid, score) for pid, score, _doc in hits]

    def size(self) -> int:
        return self._repo.count({"embedding": {"$exists": True}})


class LocalVectorIndex(VectorIndex):
    """In-process exact cosine index, rebuilt lazily when marked stale."""

    backend = "local"

    def __init__(self, repo: PaperRepository, model: str) -> None:
        self._repo = repo
        self._model = model
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._lock = Lock()
        self._stale = True

    def invalidate(self) -> None:
        with self._lock:
            self._stale = True

    def _ensure_loaded(self) -> None:
        if not self._stale and self._matrix is not None:
            return
        with self._lock:
            if not self._stale and self._matrix is not None:
                return
            ids: list[str] = []
            rows: list[np.ndarray] = []
            for doc in self._repo.iter_embeddings(self._model):
                emb = doc.get("embedding") or {}
                vector = emb.get("vector")
                if not vector:
                    continue
                ids.append(doc["_id"])
                rows.append(np.asarray(vector, dtype=np.float32))
            if rows:
                matrix = np.vstack(rows)
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._matrix = (matrix / norms).astype(np.float32, copy=False)
            else:
                self._matrix = np.zeros((0, 0), dtype=np.float32)
            self._ids = ids
            self._stale = False
            log.info("local vector index built: %d vectors (model=%s)", len(ids), self._model)

    def search(self, vector: np.ndarray, limit: int) -> list[tuple[str, float]]:
        self._ensure_loaded()
        if self._matrix is None or self._matrix.size == 0:
            return []
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query)) or 1.0
        query = query / norm
        if query.shape[0] != self._matrix.shape[1]:
            log.warning(
                "query dim %d != index dim %d - embedding model changed; reindex needed",
                query.shape[0],
                self._matrix.shape[1],
            )
            return []
        scores = self._matrix @ query
        k = min(limit, scores.shape[0])
        # argpartition gets the top-k without sorting the whole array.
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(self._ids[i], float(scores[i])) for i in top]

    def size(self) -> int:
        self._ensure_loaded()
        return len(self._ids)


_index: VectorIndex | None = None
_index_lock = Lock()


def get_vector_index(
    repo: PaperRepository | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> VectorIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                s = settings or get_settings()
                r = repo or PaperRepository()
                if is_atlas(s):
                    _index = AtlasVectorIndex(r, s)
                else:
                    from .embeddings import get_embedder

                    _index = LocalVectorIndex(r, model or get_embedder(s).name)
                log.info("vector index backend: %s", _index.backend)
    return _index


def reset_vector_index() -> None:
    """Test hook / call after a model change."""
    global _index
    with _index_lock:
        _index = None


def invalidate_vector_index() -> None:
    if _index is not None:
        _index.invalidate()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


def as_payload(index: VectorIndex) -> dict[str, Any]:
    return {"backend": index.backend, "vectors": index.size()}
