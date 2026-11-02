from __future__ import annotations

import os
from pathlib import Path

from jankhunter.config import model_api_key


def test_environment_key_takes_precedence(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_API_KEY=local-value\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_API_KEY", "process-value")

    assert model_api_key(env_file) == "process-value"


def test_reads_quoted_key_without_mutating_environment(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('# local only\nMODEL_API_KEY="local-value"\n', encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    assert model_api_key(env_file) == "local-value"
    assert "MODEL_API_KEY" not in os.environ


def test_blank_or_missing_key_returns_none(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    assert model_api_key(env_file) is None
    assert model_api_key(tmp_path / "missing.env") is None
