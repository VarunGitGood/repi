from __future__ import annotations

import logging

from repi.embeddings.base import Embedder

logger = logging.getLogger(__name__)

_MODEL_ID = "BAAI/bge-small-en-v1.5"


class BgeEmbedder(Embedder):
    name = "bge"
    dim = 384

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            logger.info("Loading fastembed model %s (first use) ...", _MODEL_ID)
            from fastembed import TextEmbedding
            self._model = TextEmbedding(_MODEL_ID)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [v.tolist() for v in model.embed(texts)]
