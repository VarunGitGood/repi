"""CONFIG_PATH must not depend on which directory the process happens to start
in. Before _resolve_config_path, `repi serve` launched from any directory other
than the repo root silently fell back to class defaults (OpenAI provider, no
key) because the cwd-relative `.repi/config.json` didn't exist there."""
import json
import os
from pathlib import Path

from repi.core.config import _resolve_config_path


def test_finds_config_in_cwd(tmp_path, monkeypatch):
    (tmp_path / ".repi").mkdir()
    cfg = tmp_path / ".repi" / "config.json"
    cfg.write_text(json.dumps({"LLM_PROVIDER": "mistral"}))
    monkeypatch.chdir(tmp_path)
    assert _resolve_config_path() == cfg


def test_finds_config_in_parent_when_run_from_subdir(tmp_path, monkeypatch):
    (tmp_path / ".repi").mkdir()
    cfg = tmp_path / ".repi" / "config.json"
    cfg.write_text(json.dumps({"LLM_PROVIDER": "mistral"}))
    subdir = tmp_path / "tmp-ui-tests" / "deep"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert _resolve_config_path() == cfg


def test_falls_back_to_relative_default_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_config_path()
    # Either the cwd-relative default (fresh machine) or the repo checkout's
    # own .repi/config.json found via the package anchor — both are stable
    # locations; what matters is it never silently resolves elsewhere.
    assert resolved.name == "config.json" and resolved.parent.name == ".repi"
