"""Local sentence-transformers embeddings for RAG."""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)

_lock = threading.Lock()
DEFAULT_BATCH_SIZE = 64


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", model_name)
    return SentenceTransformer(model_name)


def warmup_embedding_model(model_name: str) -> None:
    """Load model once so first chat/index is not cold."""
    with _lock:
        model = _load_model(model_name)
        model.encode(["warmup"], batch_size=1, show_progress_bar=False, convert_to_numpy=True)


def embed_texts(
    texts: list[str],
    *,
    model_name: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Embed many texts in batched encode() calls (not one-by-one)."""
    if not texts:
        return []
    with _lock:
        model = _load_model(model_name)
        vectors = model.encode(
            texts,
            batch_size=max(8, batch_size),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    # Single tolist() for the whole matrix is much faster than per-row loops
    return vectors.tolist()
