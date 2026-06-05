from __future__ import annotations

from repi.embeddings.base import Embedder

_KNOWN = {"fastembed", "torch"}


def create_embedder(name: str) -> Embedder:
    key = (name or "").strip().lower()
    if key == "fastembed":
        from repi.embeddings.fastembed_backend import FastembedEmbedder
        return FastembedEmbedder()
    if key == "torch":
        from repi.embeddings.torch_backend import TorchEmbedder
        return TorchEmbedder()
    raise ValueError(
        f"Unknown EMBEDDING_BACKEND {name!r}. Expected one of: {sorted(_KNOWN)}."
    )
