from __future__ import annotations
import os
from repi.core.config import settings
from repi.llm.provider import LLMProvider
from repi.llm.adapters import OpenAIProvider, AnthropicProvider, OllamaProvider, GeminiProvider, MistralProvider

def create_provider_from_env() -> LLMProvider:
    """
    Creates an LLM provider based on environment variables.
    Supported: openai, anthropic, ollama, gemini, mistral.
    """
    provider_type = settings.LLM_PROVIDER.lower()
    model_name = settings.LLM_MODEL
    
    if provider_type == "openai":
        api_key = settings.LLM_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("LLM_API_KEY or OPENAI_API_KEY must be set for OpenAI provider")
        return OpenAIProvider(api_key=api_key, model=model_name or "gpt-4o")
    
    elif provider_type == "anthropic":
        api_key = settings.LLM_API_KEY or settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("LLM_API_KEY or ANTHROPIC_API_KEY must be set for Anthropic provider")
        return AnthropicProvider(api_key=api_key, model=model_name or "claude-3-5-sonnet-20240620")
    
    elif provider_type == "ollama":
        base_url = settings.OLLAMA_BASE_URL
        return OllamaProvider(base_url=base_url, model=model_name or "mistral")
    
    elif provider_type == "gemini":
        api_key = settings.LLM_API_KEY or settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
        if not api_key:
            raise ValueError("LLM_API_KEY, GEMINI_API_KEY or GOOGLE_API_KEY must be set for Gemini provider")
        return GeminiProvider(api_key=api_key, model=model_name or "gemini-1.5-pro")

    elif provider_type == "mistral":
        api_key = settings.LLM_API_KEY or settings.MISTRAL_API_KEY
        if not api_key:
            raise ValueError("LLM_API_KEY or MISTRAL_API_KEY must be set for Mistral provider")
        return MistralProvider(api_key=api_key, model=model_name or "mistral-large-latest")
    
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: '{provider_type}'. "
            "Supported values: 'openai', 'anthropic', 'ollama', 'gemini', 'mistral'."
        )
