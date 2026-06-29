"""Unit tests for `repi --version` and `repi doctor`."""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

import repi.cli as cli_mod
from repi.cli import app

runner = CliRunner()


def _isolate_config(monkeypatch, tmp_path):
    """Point the doctor's config-presence check at a tmp config so the test
    doesn't depend on whether the dev machine (or CI runner) has a real
    .repi/config.json — CI runs from a fresh checkout where it never exists."""
    cfg_dir = tmp_path / ".repi"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text("{}")
    monkeypatch.setattr(cli_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cli_mod, "CONFIG_FILE", cfg_file)


def test_version_flag_prints_version_and_exits():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    # Either a real semver or the dev fallback
    assert re.match(r"^(\d+\.\d+\.\d+|0\.0\.0\+unknown)", result.stdout.strip())


def test_doctor_passes_when_all_checks_pass(monkeypatch, tmp_path):
    """All checks mocked to PASS — doctor exits 0."""
    _isolate_config(monkeypatch, tmp_path)
    with patch("repi.cli._read_db_url", return_value="postgresql+asyncpg://x@y/z"), \
         patch("repi.cli._check_postgres", new=AsyncMock(return_value=(True, "PostgreSQL 16"))), \
         patch("repi.cli._check_pgvector", new=AsyncMock(return_value=(True, "vector 0.8.2"))), \
         patch("repi.cli._check_llm_key", return_value=(True, "sk-1…ab")):
        result = runner.invoke(app, ["doctor", "--skip-embedding"])
    assert result.exit_code == 0, result.stdout
    assert "PASS" in result.stdout
    assert "FAIL" not in result.stdout


def test_doctor_fails_when_postgres_unreachable(monkeypatch, tmp_path):
    """A failing check produces nonzero exit + FAIL in output."""
    _isolate_config(monkeypatch, tmp_path)
    with patch("repi.cli._read_db_url", return_value="postgresql+asyncpg://x@y/z"), \
         patch("repi.cli._check_postgres", new=AsyncMock(return_value=(False, "ConnectionRefusedError"))), \
         patch("repi.cli._check_llm_key", return_value=(True, "set")):
        result = runner.invoke(app, ["doctor", "--skip-embedding"])
    assert result.exit_code == 1, result.stdout
    assert "FAIL" in result.stdout
