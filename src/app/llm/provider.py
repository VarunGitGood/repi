from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class Message:
    role: str    # "system" | "user" | "assistant"
    content: str

@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        max_tokens: int = 1000,
        temperature: float = 0.0,
    ) -> str: ...

    @property
    def model_name(self) -> str: ...
