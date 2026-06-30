from __future__ import annotations

from repi.core.config import settings
from repi.llm.provider import LLMProvider
from repi.llm.adapters import (
    OpenAICompatProvider, AnthropicProvider, OllamaProvider,
    GeminiProvider, MistralProvider,
)

_PROVIDERS: dict[str, tuple[type, str, dict]] = {
    "openai":      (OpenAICompatProvider, "gpt-4o", {}),
    "openrouter":  (OpenAICompatProvider, "openai/gpt-4o", {
        "base_url": "https://openrouter.ai/api/v1",
        "provider_label": "openrouter",
    }),
    "anthropic":   (AnthropicProvider, "claude-sonnet-4-20250514", {}),
    "mistral":     (MistralProvider, "mistral-large-latest", {}),
    "gemini":      (GeminiProvider, "gemini-2.0-flash", {}),
}

SUPPORTED_PROVIDERS = list(_PROVIDERS) + ["ollama"]


def create_provider(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    provider = (provider or settings.LLM_PROVIDER).lower()
    model = model or settings.LLM_MODEL

    if provider == "ollama":
        return OllamaProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model=model or "mistral",
        )

    if provider not in _PROVIDERS:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: '{provider}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}."
        )

    adapter_cls, default_model, extra_kwargs = _PROVIDERS[provider]
    key = api_key
    if not key:
        if provider == "openrouter" and settings.OPENROUTER_API_KEY:
            key = settings.OPENROUTER_API_KEY
        else:
            key = settings.LLM_API_KEY
    if not key:
        raise ValueError(
            f"LLM_API_KEY must be set for {provider} provider"
        )
    return adapter_cls(api_key=key, model=model or default_model, **extra_kwargs)


def create_provider_from_env() -> LLMProvider:
    return create_provider()
