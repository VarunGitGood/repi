"""Fastembed (ONNX Runtime) backend for `all-MiniLM-L6-v2` (384-dim).

Default backend. Same model weights as the torch path, executed through
ONNX Runtime; vectors are byte-identical while disk/RSS are an order of
magnitude smaller.
"""
from __future__ import annotations

import logging

from repi.embeddings.base import Embedder

logger = logging.getLogger(__name__)

_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


class FastembedEmbedder(Embedder):
    name = "fastembed"
    dim = 384

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            logger.info("Loading fastembed model %s (first use) …", _MODEL_ID)
            from fastembed import TextEmbedding
            self._model = TextEmbedding(_MODEL_ID)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [v.tolist() for v in model.embed(texts)]
