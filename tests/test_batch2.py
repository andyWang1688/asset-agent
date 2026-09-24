"""1.0 第二批：安全报告 → 裁决/自动 → Vaultwarden + 脱敏资料的完整闭环。

覆盖：私密引用 [🔒 名称](private:REF_ID)、PII/unknown 默认保留并脱敏、
报告固定字段编辑契约、Vaultwarden Login/Secure Note 真实适配、文件附带整理要求、
确认的维护 Session 上下文。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.config import Settings
from app.credentials.base import SecretMetadata, SecretPayload
from app.crypto import sha256_hex
from app.ingest import receiver
from app.security import redactor, submissions
from app.security.detectors import ScanEngine
from app.security.policy import PolicyStore, default_policy
from tests.fakes import FakeCredentialStore, FakeProvider
from tests.fakes import ingest_and_finish

SECRET = "Sup3rSecret!"
PLAN = "{}"


def _store(settings):
    return PolicyStore(settings.policy_file)


def _new_session(mode: str = "maintain") -> str:
    import uuid

    sid = uuid.uuid4().hex
    db.create_session(sid, mode)
    return sid


@pytest.fixture(autouse=True)
def _knowledge_model_configured(workspace):
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


# ---- 私密引用格式 + 稳定 ref_id + 无明文 ----

async def test_private_ref_format_and_no_plaintext(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    r = await ingest_and_finish(
        settings, creds, text=f"密码 password={SECRET} 身份证 11010519491231002X",
        policy_store=store, knowledge_provider_getter=lambda: FakeProvider(PLAN),
        session_id=maintain_session,
    )
    rep = db.report_view(r["report_id"])
    assert "[🔒 password](private:pr_" in rep["preview"]
    assert "[🔒 身份证号](private:pr_" in rep["preview"]  # PII 同样以私密引用保留并脱敏
    assert SECRET not in json.dumps(rep, ensure_ascii=False)
    assert "11010519491231002X" not in json.dumps(rep, ensure_ascii=False)
    # 每个 store 条目有稳定 ref_id，且与值无可逆关系
    refs = [e["ref_id"] for e in rep["entries"] if e["action"] == "store"]
    assert refs and all(x.startswith("pr_") for x in refs)
    assert SECRET not in "".join(refs)
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert SECRET not in raw and "11010519491231002X" not in raw
    # 两个不同值 → 不同 ref_id
    assert len(set(refs)) == len(refs)


async def test_private_ref_metadata_in_report(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    r = await ingest_and_finish(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    rep = db.report_view(r["report_id"])
    entry = rep["entries"][0]
    # 安全元数据：报告/来源定位/保险柜条目与字段位置；绝不提供原值
    assert entry["ref_id"] and entry["source"] and entry["value_hash"]
    assert entry["vault"]["item_id"] and entry["vault"]["name"]
    assert SECRET not in json.dumps(entry, ensure_ascii=False)


def test_placeholder_not_reflagged_on_rescan():
    text = "资料说明 [🔒 password](private:pr_79db20f102c4141f) 结束"
    ref = redactor.private_ref("password", "pr_79db20f102c4141f")
    masked = redactor.mask_placeholders(text, valid={ref})
    findings = ScanEngine(default_policy()).scan(masked)
    assert all(f.value != "pr_79db20f102c4141f" for f in findings)
    assert all("password" not in (f.value or "") for f in findings)


def test_placeholder_not_damaged_by_llm_output_sanitize():
    text = "[🔒 password](private:pr_79db20f102c4141f) 是已保存的凭证引用"
    ref = redactor.private_ref("password", "pr_79db20f102c4141f")
    out, hits = redactor.sanitize_llm_output(text, valid={ref})
    assert out == text
    assert hits == []


# ---- PII/unknown 默认保留并脱敏 ----

async def test_pii_and_unknown_default_store(settings):
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    sid = _new_session()
    r = await ingest_and_finish(
        settings, FakeCredentialStore(), text="联系 user@example.com 手机 13812345678",
        policy_store=store, knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=sid,
    )
    assert r["pending_confirmation"] is True
    assert all(f["suggested_action"] == "store" for f in r["findings"])
    assert {f["kind"] for f in r["findings"]} == {"pii"}


# ---- 报告固定字段编辑契约 ----

async def test_confirm_applies_edits_to_vault_and_report(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    edits = {fid: {"name": "生产库密码", "vault_kind": "login", "vault_name": "prod-db"}}
    result = await submissions.confirm(
        settings, creds, store, r["submission_id"], {fid: "store"}, edits=edits,
    )
    assert creds.created[0].kind == "login"
    assert creds.created[0].name == "prod-db"
    rep = db.report_view(r["report_id"])
    entry = rep["entries"][0]
    assert entry["name"] == "生产库密码"
    assert entry["vault"]["kind"] == "login" and entry["vault"]["name"] == "prod-db"
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "[🔒 生产库密码](private:pr_" in raw


async def test_confirm_edits_secure_note_field(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, text="身份证 11010519491231002X", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    edits = {fid: {"vault_kind": "secure_note", "vault_name": "个人信息", "field_name": "身份证"}}
    await submissions.confirm(settings, creds, store, r["submission_id"], {fid: "store"}, edits=edits)
    assert creds.created[0].kind == "secure_note"
    assert creds.created[0].name == "个人信息"
    assert creds.created[0].fields == [("身份证", "11010519491231002X")]


async def test_confirm_rejects_secret_in_editable_field(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(
            settings, creds, store, r["submission_id"], {fid: "store"},
            edits={fid: {"name": SECRET}},
        )
    assert creds.created == [] and db.list_tasks() == []


async def test_confirm_rejects_unknown_finding_edit(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(
            settings, creds, store, r["submission_id"], {fid: "store"},
            edits={"ghost": {"name": "x"}},
        )
    assert creds.created == [] and db.list_tasks() == []


# ---- Vaultwarden 适配器：Login / Secure Note 真实集成（fake bw CLI） ----

def _bw_adapter(tmp_path, monkeypatch):
    from app.credentials.vaultwarden import VaultwardenAdapter

    FAKE_BW = str(Path(__file__).parent / "fake_bw.py")
    monkeypatch.setenv("BW_BINARY", FAKE_BW)
    monkeypatch.setenv("BW_EMAIL", "u@example.com")
    monkeypatch.setenv("BW_PASSWORD", "master-pass")
    monkeypatch.setenv("BW_FAKE_STATE", str(tmp_path / "state.json"))
    s = Settings()
    s.bw_config_dir = str(tmp_path / "bwcfg")
    return VaultwardenAdapter(s)


async def test_vaultwarden_login_and_secure_note_types(tmp_path, monkeypatch):
    a = _bw_adapter(tmp_path, monkeypatch)
    await a.create_secret(SecretPayload(
        name="prod-db", value="Sup3rSecret!", kind="login", username="app",
        uri="https://db.internal", note="由资产 Agent 自动保存。值哈希: aaaa000000000000",
    ))
    await a.create_secret(SecretPayload(
        name="个人信息", value="11010519491231002X", kind="secure_note",
        fields=[("身份证", "11010519491231002X")], note="由资产 Agent 自动保存。值哈希: bbbb000000000000",
    ))
    metas = await a.list_items()
    by_name = {m.name: m for m in metas}
    assert by_name["prod-db"].kind == "login"
    assert by_name["个人信息"].kind == "secure_note"
    # 幂等标识（值哈希）在内部字段，公开 note 不暴露笔记正文
    assert by_name["prod-db"].value_hash == "aaaa000000000000"
    assert by_name["prod-db"].note == ""
    # 元数据不含秘密
    assert "Sup3rSecret!" not in str(metas)
    assert "11010519491231002X" not in str(metas)


async def test_vaultwarden_list_items_keeps_actual_note(tmp_path, monkeypatch):
    a = _bw_adapter(tmp_path, monkeypatch)
    await a.create_secret(SecretPayload(name="x", value="v", kind="login", note="由资产 Agent 自动保存。值哈希: cccc000000000000"))
    metas = await a.list_items()
    assert metas[0].value_hash == "cccc000000000000"
    assert metas[0].note == ""  # 正文不进入公开元数据


# ---- 值哈希去重：同名不吞不同秘密 ----

class _Vault(FakeCredentialStore):
    def __init__(self, existing):
        super().__init__()
        self.existing = existing

    async def list_items(self):
        return [
            SecretMetadata(name=n, item_id=f"id-{n}", note="", kind=k, value_hash=h, field_name=fn)
            for n, h, k, fn in self.existing
        ]


async def test_same_name_different_secret_not_swallowed(settings, maintain_session):
    secret_a = "SecretValueAlpha99"
    existing = [("token", sha256_hex(secret_a)[:16], "secure_note", "token")]
    vault = _Vault(existing)
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    await ingest_and_finish(
        settings, vault, text="token=SecretValueBeta88", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    # 同名但不同值 → 新建条目，绝不吞掉
    assert len(vault.created) == 1
    assert vault.created[0].value == "SecretValueBeta88"


async def test_same_value_hash_reused_idempotent(settings, maintain_session):
    secret = "TokenValueGamma77"
    existing = [("token", sha256_hex(secret)[:16], "secure_note", "token")]
    vault = _Vault(existing)
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    await ingest_and_finish(
        settings, vault, text=f"token={secret}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    assert vault.created == []  # 同值复用既有条目，不重复创建


# ---- 文件附带整理要求 ----

async def test_file_instruction_scanned_and_preserved(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, filename="a.md", data="# 资料\n订单服务说明".encode(),
        instruction="请整理到项目页面，联系 user@example.com",
        policy_store=store, knowledge_provider_getter=lambda: FakeProvider(PLAN),
        session_id=maintain_session,
    )
    rep = db.report_view(r["report_id"])
    assert "user@example.com" not in rep["instruction"]
    assert "[🔒 邮箱](private:pr_" in rep["instruction"]  # 敏感值默认保留（私密引用）而非销毁
    assert "请整理到项目页面" in rep["instruction"]
    # 文件原文未被 instruction 污染：原文件内容不含 instruction 原文
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    assert "请整理到项目页面" not in view["preview"]


async def test_manual_text_has_no_instruction(settings, maintain_session):
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, FakeCredentialStore(), text="普通内容", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    assert db.report_view(r["report_id"])["instruction"] == ""


# ---- 确认的维护 Session 上下文 ----

async def test_confirm_rejects_wrong_session(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await ingest_and_finish(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(
            settings, creds, store, r["submission_id"], {fid: "store"},
            session_id="wrong-session",
        )
    assert "不一致" in str(ei.value)
    assert creds.created == [] and db.list_tasks() == []


def test_api_confirm_rejects_wrong_session(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    creds = FakeCredentialStore()
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: creds)
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider(PLAN))
    with TestClient(main.app) as client:
        client.patch("/api/settings/security", json={"mode": "confirm"})
        m = client.post("/api/chat/sessions", json={"mode": "maintain"}).json()["session_id"]
        other = client.post("/api/chat/sessions", json={"mode": "maintain"}).json()["session_id"]
        ing = client.post("/api/ingest", data={"text": f"password={SECRET}", "session_id": m}).json()
        fid = ing["findings"][0]["id"]
        # 错误 session → 400，无写入副作用
        bad = client.post(f"/api/pending/submissions/{ing['submission_id']}/confirm",
                          json={"decisions": {fid: "store"}, "session_id": other})
        assert bad.status_code == 400
        assert creds.created == [] and db.list_tasks() == []
        assert db.get_submission(ing["submission_id"])["status"] == "waiting"
