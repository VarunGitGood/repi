from __future__ import annotations
import os
from src.app.llm.provider import LLMProvider
from src.app.llm.adapters import OpenAIProvider, AnthropicProvider, OllamaProvider, GeminiProvider, MistralProvider

def create_provider_from_env() -> LLMProvider:
    """
    Creates an LLM provider based on environment variables.
    Supported: openai, anthropic, ollama.
    """
    provider_type = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = os.getenv("LLM_MODEL")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    if provider_type == "openai":
        if not api_key:
            raise ValueError("LLM_API_KEY or OPENAI_API_KEY must be set for OpenAI provider")
        return OpenAIProvider(api_key=api_key, model=model_name or "gpt-4o")
    
    elif provider_type == "anthropic":
        if not api_key:
            raise ValueError("LLM_API_KEY must be set for Anthropic provider")
        return AnthropicProvider(api_key=api_key, model=model_name or "claude-3-5-sonnet-20240620")
    
    elif provider_type == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return OllamaProvider(base_url=base_url, model=model_name or "mistral")
    
    elif provider_type == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY must be set for Gemini provider")
        return GeminiProvider(api_key=api_key, model=model_name or "gemini-1.5-pro")

    elif provider_type == "mistral":
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY must be set for Mistral provider")
        return MistralProvider(api_key=api_key, model=model_name or "mistral-large-latest")
    
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: '{provider_type}'. "
            "Supported values: 'openai', 'anthropic', 'ollama'."
        )
