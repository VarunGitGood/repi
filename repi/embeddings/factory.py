from __future__ import annotations

from repi.embeddings.base import Embedder

_KNOWN = {"fastembed", "sentence-transformers"}


def create_embedder(name: str) -> Embedder:
    key = (name or "").strip().lower()
    if key == "fastembed":
        from repi.embeddings.fastembed_backend import FastembedEmbedder
        return FastembedEmbedder()
    if key == "sentence-transformers":
        from repi.embeddings.sentence_transformers_backend import SentenceTransformersEmbedder
        return SentenceTransformersEmbedder()
    raise ValueError(
        f"Unknown EMBEDDING_BACKEND {name!r}. Expected one of: {sorted(_KNOWN)}."
    )
