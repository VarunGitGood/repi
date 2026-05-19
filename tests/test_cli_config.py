"""Unit tests for the `repi config` subcommands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repi import cli as cli_mod
from repi.cli import app

runner = CliRunner()


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR / CONFIG_FILE to a tmpdir + matching repi.core.config paths."""
    cfg_dir = tmp_path / ".repi"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps({"LLM_PROVIDER": "openai", "REPI_ENV": "production"}) + "\n")

    monkeypatch.setattr(cli_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cli_mod, "CONFIG_FILE", cfg_file)

    from repi.core import config as core_cfg
    monkeypatch.setattr(core_cfg, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(core_cfg, "CONFIG_PATH", cfg_file)

    return cfg_file


def test_config_get_returns_current_value(tmp_config):
    result = runner.invoke(app, ["config", "get", "LLM_PROVIDER"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == "openai"


def test_config_get_masks_api_keys_by_default(tmp_config):
    tmp_config.write_text(json.dumps({"OPENAI_API_KEY": "sk-abcdefghijklmnop"}) + "\n")
    result = runner.invoke(app, ["config", "get", "OPENAI_API_KEY"])
    assert result.exit_code == 0, result.stdout
    out = result.stdout.strip()
    assert "sk-abcdefghijklmnop" not in out
    assert "…" in out


def test_config_get_unmask_reveals_secret(tmp_config):
    tmp_config.write_text(json.dumps({"OPENAI_API_KEY": "sk-abcdefghijklmnop"}) + "\n")
    result = runner.invoke(app, ["config", "get", "OPENAI_API_KEY", "--unmask"])
    assert result.exit_code == 0, result.stdout
    assert "sk-abcdefghijklmnop" in result.stdout


def test_config_get_unknown_key_errors(tmp_config):
    result = runner.invoke(app, ["config", "get", "NOPE"])
    assert result.exit_code == 1
    assert "Unknown key" in result.stdout


def test_config_set_writes_value(tmp_config):
    result = runner.invoke(app, ["config", "set", "LLM_PROVIDER=anthropic"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(tmp_config.read_text())
    assert data["LLM_PROVIDER"] == "anthropic"


def test_config_set_coerces_bool(tmp_config):
    result = runner.invoke(app, ["config", "set", "ENABLE_REDIS_CACHE=false"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(tmp_config.read_text())
    assert data["ENABLE_REDIS_CACHE"] is False


def test_config_set_coerces_int(tmp_config):
    result = runner.invoke(app, ["config", "set", "UI_PORT=4040"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(tmp_config.read_text())
    assert data["UI_PORT"] == 4040


def test_config_set_rejects_unknown_key(tmp_config):
    result = runner.invoke(app, ["config", "set", "BOGUS=1"])
    assert result.exit_code == 1
    assert "Unknown key" in result.stdout


def test_config_set_rejects_malformed_pair(tmp_config):
    result = runner.invoke(app, ["config", "set", "no_equals_here"])
    assert result.exit_code == 1
    assert "KEY=VALUE" in result.stdout


def test_config_set_hides_api_key_value_in_output(tmp_config):
    result = runner.invoke(app, ["config", "set", "OPENAI_API_KEY=sk-supersecret"])
    assert result.exit_code == 0, result.stdout
    assert "sk-supersecret" not in result.stdout
    assert "<hidden>" in result.stdout
