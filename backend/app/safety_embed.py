"""MiniLM embeddings for safety recall only. Not used for catalog or intake."""

from __future__ import annotations

import os
from functools import lru_cache

MIN_COSINE = 0.55
MODEL_NAME = "all-MiniLM-L6-v2"

_MODEL = None
_MODEL_FAILED = False


def embeddings_enabled() -> bool:
    choice = os.getenv("SAFETY_EMBED_BACKEND", "auto").strip().lower() or "auto"
    return choice not in {"off", "0", "false", "none"}


def encoder():
    """Return a MiniLM encoder, or None if disabled/unavailable."""
    global _MODEL, _MODEL_FAILED
    if not embeddings_enabled():
        return None
    if _MODEL is not None:
        return _MODEL
    if _MODEL_FAILED:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(MODEL_NAME)
        return _MODEL
    except Exception:
        _MODEL_FAILED = True
        return None


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return float(sum(a * b for a, b in zip(left, right)))


@lru_cache(maxsize=256)
def _vector(text: str) -> tuple[float, ...] | None:
    model = encoder()
    if model is None or not (text or "").strip():
        return None
    raw = model.encode([text], normalize_embeddings=True)[0]
    return tuple(float(v) for v in raw)


def best_phrase_score(sentence: str, phrases: tuple[str, ...]) -> float:
    """Max cosine between a sentence and the hazard phrases."""
    query = _vector((sentence or "").strip().lower())
    if query is None:
        return 0.0
    best = 0.0
    for phrase in phrases:
        other = _vector((phrase or "").strip().lower())
        if other is None:
            continue
        best = max(best, _dot(query, other))
    return best
