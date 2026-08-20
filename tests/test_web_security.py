"""Web 安全测试：Origin/CORS 限制与写接口 CSRF 防护。"""
from fastapi.testclient import TestClient

import app.main as main
from tests.fakes import FakeCredentialStore, FakeProvider


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("OK"))
    return TestClient(main.app)


def test_foreign_origin_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/ingest", data={"text": "普通内容"},
                        headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 403


def test_same_origin_allowed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/ingest", data={"text": "普通内容"},
                        headers={"Origin": "http://127.0.0.1:8000"})
        assert r.status_code == 200


def test_no_origin_allowed_for_cli_tools(tmp_path, monkeypatch):
    # 无 Origin/Referer（curl、脚本、TestClient 场景）视为本机调用放行
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/ingest", data={"text": "普通内容"})
        assert r.status_code == 200


def test_foreign_referer_on_write_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/ingest", data={"text": "普通内容"},
                        headers={"Referer": "http://evil.example.com/form"})
        assert r.status_code == 403


def test_referer_prefix_spoof_rejected(tmp_path, monkeypatch):
    # 127.0.0.1.evil.com / localhost.attacker.com 不得通过前缀匹配绕过
    with _client(tmp_path, monkeypatch) as client:
        for evil in ("http://127.0.0.1.evil.com/form", "http://localhost.attacker.com/form"):
            r = client.post("/api/ingest", data={"text": "普通内容"}, headers={"Referer": evil})
            assert r.status_code == 403, evil


def test_localhost_referer_allowed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post("/api/ingest", data={"text": "普通内容"},
                        headers={"Referer": "http://localhost:8000/"})
        assert r.status_code == 200


def test_foreign_origin_get_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.get("/api/settings/policy", headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 403
