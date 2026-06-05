from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Embeds text into a dense vector of fixed dimension.

    Concrete implementations live alongside this module (e.g. the fastembed
    ONNX backend). Container depends on this protocol, not on any concrete
    class, so the model backend can swap behind a single config flag.
    """

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
