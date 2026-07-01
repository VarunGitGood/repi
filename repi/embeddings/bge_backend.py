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
            import onnxruntime as _ort
            from fastembed import TextEmbedding
            # Cut ~110MB RSS by disabling the onnxruntime CPU memory arena (an
            # over-allocated inference workspace). fastembed builds
            # SessionOptions internally with no hook, so we scope-patch the
            # InferenceSession constructor to flip the flag during model load
            # only. The arena governs memory *allocation*, not compute, so
            # output vectors are byte-identical — safe against pre-embedded
            # data. threads=1 right-sizes for a 1-vCPU host.
            _orig = _ort.InferenceSession

            def _no_arena(*args, **kwargs):
                so = kwargs.get("sess_options")
                if so is not None:
                    so.enable_cpu_mem_arena = False
                return _orig(*args, **kwargs)

            _ort.InferenceSession = _no_arena
            try:
                self._model = TextEmbedding(_MODEL_ID, threads=1)
            finally:
                _ort.InferenceSession = _orig
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [v.tolist() for v in model.embed(texts)]
