"""Torch backend (via sentence-transformers) for `all-MiniLM-L6-v2` (384-dim).

Reference implementation kept so eval runs can A/B torch vs ONNX. The
torch + sentence-transformers packages are not in the default install
(they are ~790 MB on disk); enable them with the `eval-compat` group:

    uv sync --group eval-compat
    # set "EMBEDDING_BACKEND": "torch" in .repi/config.json
    uv sync                           # remove the group when done

Vectors are byte-identical to the fastembed backend.
"""
from __future__ import annotations

import logging

from repi.embeddings.base import Embedder

logger = logging.getLogger(__name__)


class TorchEmbedder(Embedder):
    name = "torch"
    dim = 384

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            logger.info("Loading torch all-MiniLM-L6-v2 (first use) …")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        arr = model.encode(texts, convert_to_numpy=True)
        return arr.tolist()
