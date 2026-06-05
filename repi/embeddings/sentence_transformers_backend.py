"""sentence-transformers/torch backend for `all-MiniLM-L6-v2` (384-dim).

Kept as the protocol's reference implementation so eval runs can A/B
the two backends. NOTE: the `sentence-transformers` + `torch` packages
are NOT in the default dependency set (issue #46 removed them to fit
Railway's 512 MB tier). To use this backend for an A/B comparison:

    uv sync --group eval-compat       # installs sentence-transformers + CPU torch
    # then set "EMBEDDING_BACKEND": "sentence-transformers" in .repi/config.json
    uv sync                           # when done — drops the group again

Vectors are byte-identical to the fastembed backend; the comparison is
only useful for confirming no regression on the eval harness.
"""
from __future__ import annotations

import logging

from repi.embeddings.base import Embedder

logger = logging.getLogger(__name__)


class SentenceTransformersEmbedder(Embedder):
    name = "sentence-transformers"
    dim = 384

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            logger.info("Loading SentenceTransformer all-MiniLM-L6-v2 (first use) …")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        arr = model.encode(texts, convert_to_numpy=True)
        return arr.tolist()
