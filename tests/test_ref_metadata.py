"""私密引用安全元数据：只返回来源/会话/保险柜位置，绝不返回原值/值哈希/笔记正文。"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.ingest import receiver
from app.security.policy import PolicyStore
from tests.fakes import FakeCredentialStore, FakeProvider

SECRET = "Sup3rSecret!"


@pytest.fixture(autouse=True)
def _knowledge_model_configured(workspace):
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


async def test_ref_metadata_returns_safe_fields_only(settings, maintain_session):
    creds = FakeCredentialStore()
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "default"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider("{}"), session_id=maintain_session,
    )
    entry = db.report_view(r["report_id"])["entries"][0]
    ref_id = entry["ref_id"]
    meta = db.find_ref_metadata(ref_id)
    assert meta is not None
    assert meta["ref_id"] == ref_id
    assert meta["name"] and meta["source"]
    assert meta["vault_name"] and meta["item_id"]
    serialized = json.dumps(meta, ensure_ascii=False)
    assert SECRET not in serialized
    # 不返回原值、值哈希、笔记正文
    assert "value_hash" not in meta
    assert "note" not in meta
    assert "value" not in meta


async def test_ref_metadata_rejects_unsaved_pending(settings, maintain_session):
    """确认模式下 pending（尚未写入保险柜）的引用不提供位置。"""
    creds = FakeCredentialStore()
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider("{}"), session_id=maintain_session,
    )
    entry = db.report_view(r["report_id"])["entries"][0]
    assert db.find_ref_metadata(entry["ref_id"]) is None


def test_reports_list_include_instruction(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("{}"))
    with TestClient(main.app) as client:
        sid = client.post("/api/chat/sessions", json={"mode": "maintain"}).json()["session_id"]
        client.patch("/api/settings/security", json={"mode": "confirm"})
        client.post(
            "/api/ingest",
            data={"session_id": sid, "text": "请整理到项目，联系 user@example.com"},
            files={"file": ("a.txt", b"ordinary document", "text/plain")},
        )
        rows = client.get("/api/reports", params={"session_id": sid}).json()
        assert rows[0]["instruction"]
        assert "user@example.com" not in rows[0]["instruction"]


def test_ref_endpoint_404_unknown_and_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("{}"))
    with TestClient(main.app) as client:
        unknown = client.get("/api/refs/pr_0000000000000000")
        assert unknown.status_code == 404
