"""模型下载服务（issue #15）：推荐/自定义 HF 模型下载、进度查询、持久卷、失败指引、幂等。"""

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.query import model_download, retrieval_config
from app.query.embeddings import build_embedding_provider
from tests.fakes import FakeCredentialStore, FakeProvider


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))
    return TestClient(main.app)


def _body(model: str):
    return {"provider": "sentence-transformers", "model": model}


def _write_snapshot(local_dir, files=("config.json", "model.safetensors")):
    target = Path(local_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name in files:
        (target / name).write_text("{}")
    return target


def _wait_status(client, model, want, timeout=5.0):
    deadline = time.time() + timeout
    view = None
    while time.time() < deadline:
        view = client.get("/api/settings/retrieval/download/status", params={"model": model}).json()
        if view["status"] == want:
            return view
        time.sleep(0.01)
    raise AssertionError(f"状态未在 {timeout}s 内达到 {want}：{view}")


def _reset_manager(monkeypatch):
    manager = model_download.DownloadManager()
    monkeypatch.setattr(model_download, "manager", manager)
    return manager


def test_progress_bar_aggregates_into_job():
    job = model_download.Job("BAAI/bge-small-zh-v1.5")
    model_download._local.job = job
    try:
        transfer = model_download._Progress(desc="Downloading bytes", total=1000)
        transfer.update(250)
        assert job.bytes_done == 250
        assert job.bytes_total == 1000
        files = model_download._Progress(desc="Fetching 2 files", total=2)
        files.update(1)
        assert job.files_done == 1
        assert job.files_total == 2
        assert job.snapshot()["progress"] == 50.0
        files.update(1)
        assert job.snapshot()["progress"] == 100.0
    finally:
        model_download._local.job = None


def test_download_recommended_and_custom_models(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    downloaded = []

    def fake_snapshot(repo_id, local_dir, tqdm_class, **kw):
        downloaded.append(repo_id)
        _write_snapshot(local_dir)
        return str(local_dir)

    monkeypatch.setattr(model_download, "snapshot_download", fake_snapshot)
    with _client(tmp_path, monkeypatch) as client:
        for model in ("BAAI/bge-small-zh-v1.5", "my-org/custom-bge"):
            resp = client.post("/api/settings/retrieval/download", json=_body(model))
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
            assert resp.json()["started"] is True
            view = _wait_status(client, model, "done")
            assert view["progress"] == 100.0
    assert downloaded == ["BAAI/bge-small-zh-v1.5", "my-org/custom-bge"]
    data_dir = Path(tmp_path) / "ws" / ".asset-assistant"
    assert (data_dir / "models" / "hf" / "BAAI" / "bge-small-zh-v1.5" / "config.json").is_file()
    assert (data_dir / "models" / "hf" / "my-org" / "custom-bge" / "config.json").is_file()


def test_download_progress_queryable_and_non_blocking(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_snapshot(repo_id, local_dir, tqdm_class, **kw):
        files = tqdm_class(desc="Fetching 2 files", total=2)
        transfer = tqdm_class(desc="Downloading bytes", total=1000)
        files.update(1)
        transfer.update(400)
        started.set()
        release.wait(timeout=5)
        _write_snapshot(local_dir)
        files.update(1)
        transfer.update(600)
        files.close()
        transfer.close()
        return str(local_dir)

    monkeypatch.setattr(model_download, "snapshot_download", slow_snapshot)
    with _client(tmp_path, monkeypatch) as client:
        begin = time.time()
        resp = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5"))
        assert resp.status_code == 200
        assert time.time() - begin < 2, "下载 POST 必须立即返回，不得等待下载完成"
        assert started.wait(timeout=5)
        view = _wait_status(client, "BAAI/bge-small-zh-v1.5", "downloading")
        assert 0.0 < view["progress"] < 100.0
        assert view["files_done"] == 1
        assert view["files_total"] == 2
        assert view["bytes_done"] == 400
        release.set()
        view = _wait_status(client, "BAAI/bge-small-zh-v1.5", "done")
        assert view["progress"] == 100.0
        assert view["files_done"] == 2


def test_download_idempotent_running_and_done(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    calls = []
    started = threading.Event()
    release = threading.Event()

    def slow_snapshot(repo_id, local_dir, tqdm_class, **kw):
        calls.append(repo_id)
        started.set()
        release.wait(timeout=5)
        _write_snapshot(local_dir)
        return str(local_dir)

    monkeypatch.setattr(model_download, "snapshot_download", slow_snapshot)
    with _client(tmp_path, monkeypatch) as client:
        first = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5")).json()
        assert first["started"] is True
        assert started.wait(timeout=5)
        second = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5")).json()
        assert second["started"] is False
        assert second["download"]["status"] in {"queued", "downloading"}
        release.set()
        _wait_status(client, "BAAI/bge-small-zh-v1.5", "done")
        third = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5")).json()
        assert third["started"] is False
        assert third["download"]["status"] == "done"
    assert calls == ["BAAI/bge-small-zh-v1.5"], "重复请求不得重复启动下载"


def test_download_network_failure_ollama_guidance(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)

    def boom(repo_id, local_dir, tqdm_class, **kw):
        raise ConnectionError("Failed to establish a new connection")

    monkeypatch.setattr(model_download, "snapshot_download", boom)
    with _client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5"))
        assert resp.status_code == 200
        view = _wait_status(client, "BAAI/bge-small-zh-v1.5", "failed")
    assert "网络不可达" in view["error"]
    assert "Ollama" in view["error"]
    assert "ollama pull" in view["error"]


def test_download_disk_snapshot_survives_manager_restart(tmp_path, monkeypatch):
    data_dir = Path(tmp_path) / "ws" / ".asset-assistant"
    _write_snapshot(data_dir / "models" / "hf" / "BAAI" / "bge-small-zh-v1.5")
    calls = []
    monkeypatch.setattr(
        model_download, "snapshot_download",
        lambda *a, **kw: calls.append(1) or "x",
    )
    _reset_manager(monkeypatch)  # 模拟进程重启：任务表为空，磁盘快照仍在
    with _client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/settings/retrieval/download", json=_body("BAAI/bge-small-zh-v1.5")).json()
        assert resp["started"] is False
        assert resp["download"]["status"] == "done"
        view = client.get("/api/settings/retrieval/download/status",
                          params={"model": "BAAI/bge-small-zh-v1.5"}).json()
        assert view["status"] == "done"
        assert view["downloaded"] is True
    assert calls == [], "磁盘已有快照时不得再触发下载"


def test_download_unknown_model_status(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    with _client(tmp_path, monkeypatch) as client:
        view = client.get("/api/settings/retrieval/download/status", params={"model": "x/y"}).json()
    assert view["status"] == "unknown"


def test_download_rejects_other_providers(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    with _client(tmp_path, monkeypatch) as client:
        ollama = client.post("/api/settings/retrieval/download", json={"provider": "ollama", "model": "bge-m3"})
        assert ollama.status_code == 400
        assert "ollama pull" in ollama.json()["detail"]
        cloud = client.post("/api/settings/retrieval/download", json={"provider": "cloud", "model": "x"})
        assert cloud.status_code == 400
        assert "无需下载" in cloud.json()["detail"]


def test_download_rejects_invalid_model_id(tmp_path, monkeypatch):
    _reset_manager(monkeypatch)
    with _client(tmp_path, monkeypatch) as client:
        for bad in ("../escape", "a b", "", "a//b"):
            resp = client.post("/api/settings/retrieval/download", json=_body(bad))
            assert resp.status_code == 400, bad


def test_friendly_download_error_missing_model():
    error = model_download.friendly_download_error(ValueError("404 Client Error: Entry Not Found"))
    assert "模型不存在" in error
    assert "Ollama" in error


def test_downloaded_snapshot_preferred_by_embedders(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    monkeypatch.setenv("WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("DATA_DIR", str(ws / ".asset-assistant"))
    settings = Settings()
    snapshot = model_download.model_snapshot_dir(settings.data_dir, "BAAI/bge-small-zh-v1.5")
    _write_snapshot(snapshot)

    embedder = build_embedding_provider(settings)
    assert embedder.model_name == str(snapshot)

    page_embedder = retrieval_config.build_page_embedder(
        settings, {"provider": "sentence-transformers", "model": "BAAI/bge-small-zh-v1.5"}
    )
    assert page_embedder.model_name == str(snapshot)

    test_embedder = retrieval_config.build_test_embedder(
        settings, provider="sentence-transformers", model="BAAI/bge-small-zh-v1.5"
    )
    assert test_embedder.model_name == str(snapshot)


def test_downloaded_snapshot_preferred_by_reranker(tmp_path, monkeypatch):
    import app.query.hybrid as hybrid

    ws = tmp_path / "ws"
    monkeypatch.setenv("WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("DATA_DIR", str(ws / ".asset-assistant"))
    settings = Settings()
    snapshot = model_download.model_snapshot_dir(settings.data_dir, "BAAI/bge-reranker-base")
    _write_snapshot(snapshot)

    seen = {}

    class FakeRerank:
        def __init__(self, model, **kwargs):
            seen["model"] = model

    monkeypatch.setattr(hybrid, "SentenceTransformerRerank", FakeRerank)
    hybrid.build_reranker(settings, mode="local")
    assert seen["model"] == str(snapshot)
