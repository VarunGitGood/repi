"""Lock the invariant that Settings reads only from config.json.

If anyone re-enables the env source (by removing the
`settings_customise_sources` override on Settings), the leak test below fails
immediately. The full reasoning lives in
plans/hmm-i-want-the-abstract-raccoon.md.
"""
from repi.core.config import Settings


def test_settings_ignores_env_vars(monkeypatch):
    # Every secret-looking field should resolve to its class default (None
    # for *_API_KEY, even when the shell env tries to inject a value.
    monkeypatch.setenv("MISTRAL_API_KEY", "should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-leak")
    monkeypatch.setenv("LLM_API_KEY", "should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://evil:evil@evil:5432/evil")

    s = Settings()

    assert s.MISTRAL_API_KEY is None
    assert s.OPENAI_API_KEY is None
    assert s.ANTHROPIC_API_KEY is None
    assert s.GEMINI_API_KEY is None
    assert s.LLM_API_KEY is None
    # DATABASE_URL falls back to the class default, not the env injection.
    assert "evil" not in s.DATABASE_URL


def test_settings_accepts_kwargs(monkeypatch):
    # init kwargs (the path used by get_settings() after reading config.json)
    # remain the *only* way real values arrive.
    monkeypatch.setenv("MISTRAL_API_KEY", "from-env-should-lose")
    s = Settings(MISTRAL_API_KEY="from-kwargs-should-win")
    assert s.MISTRAL_API_KEY == "from-kwargs-should-win"
