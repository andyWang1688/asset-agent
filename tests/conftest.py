import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    monkeypatch.setenv("WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("DATA_DIR", str(ws / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    db.init(ws / ".asset-assistant" / "app.db")
    return ws


from app.config import Settings  # noqa: E402


@pytest.fixture
def settings(workspace):
    s = Settings()
    s.ensure_dirs()
    return s
