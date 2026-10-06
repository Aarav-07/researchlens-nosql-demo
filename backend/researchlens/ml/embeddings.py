"""Embedding layer.

One interface, two backends:

* `SentenceTransformerEmbedder` - real semantic embeddings (all-MiniLM-L6-v2 by
  default). Requires `sentence-transformers` and a one-time model download.
* `HashingEmbedder` - dependency-free deterministic fallback (hashed word +
  bigram features, L2-normalized). Weaker than a trained model but it keeps the
  whole pipeline runnable offline and makes tests fast and deterministic.

`get_embedder()` resolves `RL_EMBEDDING_BACKEND` (auto | sentence_transformers |
hashing) and caches the instance, so the model loads once per process.
"""
from __future__ import annotations

import hashlib
import re
import time
from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np

from ..config import Settings, get_settings
from ..logging_conf import get_logger

log = get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_embedder: "Embedder | None" = None


class Embedder(ABC):
    """Maps text to a unit-norm float32 vector."""

    name: str
    dim: int
    # True when this is the degraded stand-in rather than the configured model.
    # Callers use it to refuse corpus-wide writes in a weaker vector space.
    is_fallback: bool = False

    @abstractmethod
    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Returns shape (len(texts), dim), float32, L2-normalized rows."""

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} {self.name} dim={self.dim}>"


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32, copy=False)


class HashingEmbedder(Embedder):
    """Hashing-trick embedder: unigrams + bigrams, sublinear term weighting."""

    is_fallback = True

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _tokens(self, text: str) -> list[str]:
        words = _TOKEN.findall(text.lower())
        bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
        return words + bigrams

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        return int.from_bytes(digest, "little") % self.dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            counts: dict[int, float] = {}
            for token in self._tokens(text or ""):
                idx = self._bucket(token)
                counts[idx] = counts.get(idx, 0.0) + 1.0
            for idx, count in counts.items():
                # Sublinear scaling: the 10th "the" should not dominate.
                out[row, idx] = 1.0 + np.log(count)
        return _l2_normalize(out)


class SentenceTransformerEmbedder(Embedder):
    is_fallback = False

    def __init__(self, model_name: str, batch_size: int = 32, local_only: bool = False) -> None:
        from sentence_transformers import SentenceTransformer  # local import: optional dep

        log.info("loading embedding model %s (first run downloads weights)", model_name)
        self._model = (
            SentenceTransformer(model_name, local_files_only=True)
            if local_only
            else SentenceTransformer(model_name)
        )
        self.name = model_name
        # Method was renamed in sentence-transformers 5.x.
        dim_getter = getattr(
            self._model, "get_embedding_dimension", None
        ) or self._model.get_sentence_embedding_dimension
        self.dim = int(dim_getter())
        self._batch_size = batch_size
        log.info("embedding model ready: %s dim=%d", model_name, self.dim)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


def build_embedder(settings: Settings | None = None) -> Embedder:
    """Load the configured model, or the fallback if it truly cannot be had.

    Two processes starting at once can collide on the model cache, and the hub
    can be briefly unreachable. Both are transient, and both used to end in a
    silent downgrade to the hashing embedder, which then rewrote every vector in
    the corpus in a weaker space. So: retry, then retry from the local cache
    only, and log the downgrade at ERROR when it does happen.
    """
    s = settings or get_settings()
    backend = (s.embedding_backend or "auto").lower()

    if backend == "hashing":
        return HashingEmbedder(s.embedding_dim_fallback)

    attempts = (
        {"local_only": False},
        {"local_only": False},  # transient hub or cache-lock races
        {"local_only": True},  # network down, weights already cached
    )
    last_error: Exception | None = None
    for index, options in enumerate(attempts, start=1):
        try:
            return SentenceTransformerEmbedder(
                s.embedding_model_name, s.embedding_batch_size, **options
            )
        except Exception as exc:  # missing dep, no network, corrupt cache
            last_error = exc
            log.warning("embedding model load attempt %d/%d failed: %s", index, len(attempts), exc)
            time.sleep(1.5 * index)

    if backend == "sentence_transformers":
        raise RuntimeError(f"could not load {s.embedding_model_name}: {last_error}")

    log.error(
        "FALLING BACK to the hashing embedder: %s could not be loaded (%s). "
        "Search quality will be much worse, and papers embedded now will not share "
        "a vector space with the rest of the corpus.",
        s.embedding_model_name,
        last_error,
    )
    return HashingEmbedder(s.embedding_dim_fallback)


def get_embedder(settings: Settings | None = None) -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = build_embedder(settings)
    return _embedder


def reset_embedder() -> None:
    """Test hook - drops the cached instance."""
    global _embedder
    _embedder = None
