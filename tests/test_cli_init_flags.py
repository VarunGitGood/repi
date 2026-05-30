"""Tests for `repi init` non-interactive flags (--provider, --api-key, --api-key-stdin)."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from repi import cli as cli_mod
from repi.cli import app

runner = CliRunner()


@pytest.fixture
def tmp_init_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR/CONFIG_FILE to a tmpdir and stub out the postgres calls.

    `init` always calls _wait_for_postgres + _apply_schema after writing the
    config, regardless of --with-docker. We don't have a real DB in unit tests,
    so stub both to no-ops.
    """
    cfg_dir = tmp_path / ".repi"
    cfg_file = cfg_dir / "config.json"

    monkeypatch.setattr(cli_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cli_mod, "CONFIG_FILE", cfg_file)

    async def _ok(*_args, **_kwargs):
        return True

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cli_mod, "_wait_for_postgres", _ok)
    monkeypatch.setattr(cli_mod, "_apply_schema", _noop)

    return cfg_file


def test_provider_and_api_key_skip_prompts(tmp_init_dir):
    result = runner.invoke(
        app, ["init", "--provider", "mistral", "--api-key", "sk-from-flag"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(tmp_init_dir.read_text())
    assert data["LLM_PROVIDER"] == "mistral"
    assert data["MISTRAL_API_KEY"] == "sk-from-flag"


def test_api_key_stdin(tmp_init_dir):
    result = runner.invoke(
        app,
        ["init", "--provider", "anthropic", "--api-key-stdin"],
        input="sk-from-stdin\n",
    )
    assert result.exit_code == 0, result.output
    data = json.loads(tmp_init_dir.read_text())
    assert data["LLM_PROVIDER"] == "anthropic"
    assert data["ANTHROPIC_API_KEY"] == "sk-from-stdin"


def test_api_key_stdin_empty_errors(tmp_init_dir):
    result = runner.invoke(
        app,
        ["init", "--provider", "anthropic", "--api-key-stdin"],
        input="",
    )
    assert result.exit_code == 2


def test_api_key_and_api_key_stdin_are_mutually_exclusive(tmp_init_dir):
    result = runner.invoke(
        app,
        [
            "init",
            "--provider",
            "mistral",
            "--api-key",
            "sk-one",
            "--api-key-stdin",
        ],
        input="sk-two\n",
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output.lower()


def test_invalid_provider_errors(tmp_init_dir):
    result = runner.invoke(
        app, ["init", "--provider", "azure-openai", "--api-key", "sk-x"]
    )
    assert result.exit_code == 2
    assert "unknown" in result.output.lower()


def test_ollama_provider_needs_no_api_key(tmp_init_dir):
    # ollama isn't in PROVIDER_KEY_ENV so the key prompt/flag is skipped.
    result = runner.invoke(app, ["init", "--provider", "ollama"])
    assert result.exit_code == 0, result.output
    data = json.loads(tmp_init_dir.read_text())
    assert data["LLM_PROVIDER"] == "ollama"
    # No *_API_KEY field should have been written.
    assert not any(k.endswith("_API_KEY") for k in data)
