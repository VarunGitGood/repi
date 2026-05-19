"""Unit tests for `repi --version` and `repi doctor`."""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from repi.cli import app

runner = CliRunner()


def test_version_flag_prints_version_and_exits():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    # Either a real semver or the dev fallback
    assert re.match(r"^(\d+\.\d+\.\d+|0\.0\.0\+unknown)", result.stdout.strip())


def test_doctor_passes_when_all_checks_pass():
    """All checks mocked to PASS — doctor exits 0."""
    with patch("repi.cli._read_db_url", return_value="postgresql+asyncpg://x@y/z"), \
         patch("repi.cli._check_postgres", new=AsyncMock(return_value=(True, "PostgreSQL 16"))), \
         patch("repi.cli._check_pgvector", new=AsyncMock(return_value=(True, "vector 0.8.2"))), \
         patch("repi.cli._check_redis", new=AsyncMock(return_value=(True, "PING ok"))), \
         patch("repi.cli._check_llm_key", return_value=(True, "sk-1…ab")):
        result = runner.invoke(app, ["doctor", "--skip-embedding"])
    assert result.exit_code == 0, result.stdout
    assert "PASS" in result.stdout
    assert "FAIL" not in result.stdout


def test_doctor_fails_when_postgres_unreachable():
    """A failing check produces nonzero exit + FAIL in output."""
    with patch("repi.cli._read_db_url", return_value="postgresql+asyncpg://x@y/z"), \
         patch("repi.cli._check_postgres", new=AsyncMock(return_value=(False, "ConnectionRefusedError"))), \
         patch("repi.cli._check_redis", new=AsyncMock(return_value=(True, "PING ok"))), \
         patch("repi.cli._check_llm_key", return_value=(True, "set")):
        result = runner.invoke(app, ["doctor", "--skip-embedding"])
    assert result.exit_code == 1, result.stdout
    assert "FAIL" in result.stdout
