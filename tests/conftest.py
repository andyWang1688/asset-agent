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


class _NoopReranker:
    """重排测试替身：保持召回顺序不变，不加载任何模型。"""

    def postprocess_nodes(self, nodes, query_bundle=None):
        return nodes


@pytest.fixture(autouse=True)
def _default_local_embedding(monkeypatch):
    """测试默认不加载真实模型：装配路径（引擎/索引构建）的 embedding 工厂换成确定性替身，
    重排器换成无模型替身。"""
    from app.query import hybrid, retrieval
    from tests.fakes import KeywordEmbedding

    monkeypatch.setattr(hybrid, "build_embedding_provider", lambda settings: KeywordEmbedding())
    monkeypatch.setattr(retrieval, "build_embedding_provider", lambda settings: KeywordEmbedding())
    monkeypatch.setattr(hybrid, "SentenceTransformerRerank", lambda **kwargs: _NoopReranker())
