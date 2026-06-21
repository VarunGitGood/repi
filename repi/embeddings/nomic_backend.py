from __future__ import annotations

import logging

from repi.embeddings.base import Embedder

logger = logging.getLogger(__name__)

_MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"


class NomicEmbedder(Embedder):
    name = "nomic"
    dim = 768

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
        prefixed = [f"search_document: {t}" for t in texts]
        return [v.tolist() for v in model.embed(prefixed)]
