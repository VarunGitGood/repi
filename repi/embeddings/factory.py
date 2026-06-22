from __future__ import annotations

from repi.embeddings.base import Embedder

_KNOWN = {"fastembed", "torch", "nomic", "bge"}


def create_embedder(name: str) -> Embedder:
    key = (name or "").strip().lower()
    if key == "fastembed":
        from repi.embeddings.fastembed_backend import FastembedEmbedder
        return FastembedEmbedder()
    if key == "torch":
        from repi.embeddings.torch_backend import TorchEmbedder
        return TorchEmbedder()
    if key == "nomic":
        from repi.embeddings.nomic_backend import NomicEmbedder
        return NomicEmbedder()
    if key == "bge":
        from repi.embeddings.bge_backend import BgeEmbedder
        return BgeEmbedder()
    raise ValueError(
        f"Unknown EMBEDDING_BACKEND {name!r}. Expected one of: {sorted(_KNOWN)}."
    )
