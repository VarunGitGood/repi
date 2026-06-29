"""Lock the invariant that Settings reads only from config.json.

If anyone re-enables the env source (by removing the
`settings_customise_sources` override on Settings), the leak test below fails
immediately. The full reasoning lives in
plans/hmm-i-want-the-abstract-raccoon.md.
"""
from repi.core.config import Settings


def test_settings_ignores_env_vars(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://evil:evil@evil:5432/evil")

    s = Settings()

    assert s.LLM_API_KEY is None
    assert "evil" not in s.DATABASE_URL


def test_settings_accepts_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-env-should-lose")
    s = Settings(LLM_API_KEY="from-kwargs-should-win")
    assert s.LLM_API_KEY == "from-kwargs-should-win"


def test_legacy_key_migration():
    s = Settings(OPENAI_API_KEY="sk-old-style")
    assert s.LLM_API_KEY == "sk-old-style"


def test_legacy_key_does_not_overwrite_explicit():
    s = Settings(LLM_API_KEY="sk-explicit", ANTHROPIC_API_KEY="sk-legacy")
    assert s.LLM_API_KEY == "sk-explicit"
