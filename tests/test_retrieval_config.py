"""检索配置持久化 + API（issue #14）：页面写入优先、Key 加密不回显、测试端点、环境变量兼容。"""

import json

from fastapi.testclient import TestClient

import app.main as main
from app import crypto, db
from app.query import retrieval, retrieval_config
from app.query.embeddings import build_embedding_provider, OllamaEmbedding
from tests.fakes import FakeCredentialStore, FakeProvider


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))
    return TestClient(main.app)


def _local_body(**overrides):
    body = {
        "provider": "sentence-transformers",
        "model": "BAAI/bge-small-zh-v1.5",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-base",
        "cloud_base_url": "",
        "cloud_api_key": "",
        "cloud_ack": False,
    }
    body.update(overrides)
    return body


def test_env_defaults_exposed_when_unconfigured(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        view = client.get("/api/settings/retrieval").json()
    assert view["configured"] is False
    assert view["source"] == "env"
    assert view["provider"] == "sentence-transformers"
    assert view["model"] == "BAAI/bge-small-zh-v1.5"
    assert view["reranker_enabled"] is True
    assert view["reranker_model"] == "BAAI/bge-reranker-base"
    assert view["cloud_api_key_set"] is False
    assert "BAAI/bge-small-zh-v1.5" in view["recommended"]["embeddings"]["sentence-transformers"]


def test_save_and_read_local_custom_model(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        saved = client.post(
            "/api/settings/retrieval",
            json=_local_body(model="my-org/custom-bge", reranker_enabled=False),
        )
        assert saved.status_code == 200
        assert saved.json()["ok"] is True
        view = client.get("/api/settings/retrieval").json()
    assert view["configured"] is True
    assert view["source"] == "page"
    assert view["model"] == "my-org/custom-bge"
    assert view["reranker_enabled"] is False


def test_cloud_requires_endpoint_and_ack(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        missing_url = client.post("/api/settings/retrieval", json=_local_body(provider="cloud", model="text-embedding-3-small"))
        assert missing_url.status_code == 400
        missing_ack = client.post(
            "/api/settings/retrieval",
            json=_local_body(provider="cloud", model="text-embedding-3-small",
                             cloud_base_url="https://embed.example/v1", cloud_api_key="sk-secret"),
        )
        assert missing_ack.status_code == 400 and "勾选" in missing_ack.json()["detail"]
        ok = client.post(
            "/api/settings/retrieval",
            json=_local_body(provider="cloud", model="text-embedding-3-small",
                             cloud_base_url="https://embed.example/v1",
                             cloud_api_key="sk-secret-123", cloud_ack=True),
        )
        assert ok.status_code == 200
        row = db.get_retrieval_config()
        view = client.get("/api/settings/retrieval").json()
        key = main.app.state.ctx.settings.local_key()
    assert "sk-secret-123" not in json.dumps(dict(row), ensure_ascii=False)
    assert crypto.open_sealed(key, row["cloud_api_key_enc"]) == b"sk-secret-123"
    assert view["cloud_api_key_set"] is True
    assert "sk-secret" not in json.dumps(view)


def test_cloud_key_kept_when_left_blank(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post(
            "/api/settings/retrieval",
            json=_local_body(provider="cloud", model="text-embedding-3-small",
                             cloud_base_url="https://embed.example/v1",
                             cloud_api_key="sk-original", cloud_ack=True),
        )
        client.post(
            "/api/settings/retrieval",
            json=_local_body(provider="cloud", model="text-embedding-3-large",
                             cloud_base_url="https://embed.example/v1", cloud_ack=True),
        )
        row = db.get_retrieval_config()
        key = main.app.state.ctx.settings.local_key()
    assert crypto.open_sealed(key, row["cloud_api_key_enc"]) == b"sk-original"


def test_unknown_provider_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/settings/retrieval", json=_local_body(provider="quantum"))
    assert r.status_code == 400


def test_reset_restores_env_semantics(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/settings/retrieval", json=_local_body(model="BAAI/bge-large-zh-v1.5"))
        assert client.get("/api/settings/retrieval").json()["configured"] is True
        client.delete("/api/settings/retrieval")
        view = client.get("/api/settings/retrieval").json()
    assert view["configured"] is False
    assert view["source"] == "env"
    assert view["model"] == "BAAI/bge-small-zh-v1.5"


class _FakeEmbedder:
    def get_text_embedding(self, text: str):
        assert text == "资产检索连通性测试"
        return [0.1, 0.2, 0.3, 0.4]


def test_test_endpoint_returns_dimension(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_config, "build_test_embedder", lambda settings, **kw: _FakeEmbedder())
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/settings/retrieval/test", json=_local_body(model="BAAI/bge-small-zh-v1.5"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "dimension": 4}


class _BrokenEmbedder:
    def get_text_embedding(self, text: str):
        raise OSError("Failed to connect to huggingface.co: Connection refused")


def test_test_endpoint_friendly_error(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_config, "build_test_embedder", lambda settings, **kw: _BrokenEmbedder())
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/settings/retrieval/test", json=_local_body(model="BAAI/bge-small-zh-v1.5"))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "Ollama" in body["error"]


def test_page_config_wins_over_env_for_embedding(settings, monkeypatch):
    db.save_retrieval_config("ollama", "bge-m3", 1, "BAAI/bge-reranker-base", "", "")
    monkeypatch.setattr(settings, "embedding_local_backend", "sentence-transformers")
    embedder = build_embedding_provider(settings)
    assert isinstance(embedder, OllamaEmbedding)
    assert embedder.model_name == "bge-m3"


def test_page_reranker_off_wins_over_env(settings, monkeypatch):
    from app.query import hybrid

    db.save_retrieval_config("sentence-transformers", "BAAI/bge-small-zh-v1.5", 0, "", "", "")
    monkeypatch.setattr(settings, "reranker", "local")
    assert hybrid.build_reranker(settings) is None


def test_index_invalidated_only_on_incompatible_change(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        settings = main.app.state.ctx.settings
        idx = retrieval.index_dir(settings)
        idx.mkdir(parents=True, exist_ok=True)
        (idx / "index_store.json").write_text("{}", encoding="utf-8")
        assert retrieval.has_index(settings)

        first = client.post("/api/settings/retrieval", json=_local_body(model="BAAI/bge-small-zh-v1.5"))
        # 与 env 默认同签名：不删索引
        assert first.json()["index_invalidated"] is False
        assert retrieval.has_index(settings)

        changed = client.post("/api/settings/retrieval", json=_local_body(model="BAAI/bge-large-zh-v1.5"))
        # 模型变更：向量不兼容，删除派生索引（下次问答自动重建）
        assert changed.json()["index_invalidated"] is True
        assert not retrieval.has_index(settings)
