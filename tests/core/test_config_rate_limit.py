from repi.core.config import Settings


def test_llm_rate_limit_uses_global_default_when_no_override():
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        LLM_MAX_CALLS_PER_MIN=60,
    )

    assert settings.llm_max_calls_per_min_for_provider() == 60


def test_llm_rate_limit_uses_provider_override_when_present():
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="mistral",
        LLM_MAX_CALLS_PER_MIN=60,
        LLM_MAX_CALLS_PER_MIN_MISTRAL=3,
    )

    assert settings.llm_max_calls_per_min_for_provider() == 3
    assert settings.llm_max_calls_per_min_for_provider("openai") == 60
