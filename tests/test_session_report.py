"""1.0 首批：Session 固定模式权限 + 安全报告/任务关联。

覆盖：Session 显式创建/固定模式、问答写入拒绝、维护输入与报告关联 Session、
自动与确认的任务创建时机、确认后报告锁定与无明文持久化、多轮维护、
恢复历史与查看任务的契约。"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.ingest import receiver
from app.security import submissions
from app.security.policy import PolicyStore
from tests.fakes import FakeCredentialStore, FakeProvider

SECRET = "Sup3rSecret!"
PLAN = "{}"


def _store(settings):
    return PolicyStore(settings.policy_file)


@pytest.fixture(autouse=True)
def _knowledge_model_configured(workspace):
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


def _new_session(mode: str) -> str:
    sid = uuid.uuid4().hex
    db.create_session(sid, mode)
    return sid


# ---- Session 显式创建 / 固定模式 ----

def test_create_session_fixed_mode():
    sid = _new_session(db.SESSION_MAINTAIN)
    assert db.session_mode(sid) == "maintain"
    # 幂等：同模式重复创建不报错
    db.create_session(sid, db.SESSION_MAINTAIN)
    assert db.session_mode(sid) == "maintain"
    # 固定：不能切换模式
    with pytest.raises(ValueError):
        db.create_session(sid, db.SESSION_ASK)
    # 非法模式
    with pytest.raises(ValueError):
        db.create_session(uuid.uuid4().hex, "nope")


def test_list_sessions_includes_mode():
    a = _new_session(db.SESSION_ASK)
    m = _new_session(db.SESSION_MAINTAIN)
    modes = {s["session_id"]: s["mode"] for s in db.list_sessions()}
    assert modes[a] == "ask" and modes[m] == "maintain"


# ---- 问答写入拒绝 ----

async def test_ingest_rejected_on_ask_session(settings, ask_session):
    creds = FakeCredentialStore()
    with pytest.raises(ValueError) as ei:
        await receiver.ingest(
            settings, creds, text=f"password={SECRET}",
            knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=ask_session,
        )
    assert "维护会话" in str(ei.value)
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.list_reports() == []


async def test_ingest_rejected_without_session(settings):
    creds = FakeCredentialStore()
    with pytest.raises(ValueError) as ei:
        await receiver.ingest(
            settings, creds, text=f"password={SECRET}",
            knowledge_provider_getter=lambda: FakeProvider(PLAN),
        )
    assert "维护会话" in str(ei.value)
    assert creds.created == []
    assert db.list_tasks() == []


async def test_confirm_rejected_when_session_not_maintain(settings):
    """伪造 ask 会话关联提交 → 确认被拒，不能写。"""
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    sid = _new_session(db.SESSION_MAINTAIN)
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=sid,
    )
    # 模拟攻击者把提交关联到一个 ask 会话
    db._w("UPDATE chat_sessions SET mode='ask' WHERE session_id=?", (sid,))
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(settings, creds, store, r["submission_id"], {fid: "store"})
    assert "维护会话" in str(ei.value)
    assert db.list_tasks() == []
    assert creds.created == []
    assert list(settings.inbox_dir.glob("*")) == []


# ---- 自动模式：直接执行 + 报告锁定 + 任务关联 ----

async def test_auto_mode_creates_task_and_locked_report(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET} 说明", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    assert "pending_confirmation" not in r
    assert r["task_id"] and r["report_id"]
    t = db.get_task(r["task_id"])
    assert t["session_id"] == maintain_session
    assert t["report_id"] == r["report_id"]
    rep = db.report_view(r["report_id"])
    assert rep["status"] == "auto"
    assert rep["session_id"] == maintain_session
    assert rep["confirmed_at"]
    assert SECRET not in json.dumps(rep, ensure_ascii=False)
    entry = rep["entries"][0]
    assert entry["type"] == "credential"
    assert entry["name"] == "password"
    assert entry["action"] == "store"
    assert entry["vault"]["item_id"]
    assert "[🔒 password](private:pr_" in rep["preview"]
    assert creds.created[0].value == SECRET


# ---- 确认模式：任务创建时机 + 确认后报告锁定 ----

async def test_confirm_mode_no_task_until_confirm(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    assert r["pending_confirmation"] is True and r["report_id"]
    assert db.list_tasks() == []  # 确认前无任务
    rep = db.report_view(r["report_id"])
    assert rep["status"] == "pending" and rep["session_id"] == maintain_session
    assert rep["confirmed_at"] is None
    assert SECRET not in json.dumps(rep, ensure_ascii=False)

    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    result = await submissions.confirm(settings, creds, store, r["submission_id"], {fid: "store"})
    assert result["task_id"]
    t = db.get_task(result["task_id"])
    assert t["session_id"] == maintain_session and t["report_id"] == r["report_id"]
    rep = db.report_view(r["report_id"])
    assert rep["status"] == "confirmed" and rep["confirmed_at"]
    assert rep["entries"][0]["vault"]["item_id"]
    # 锁定：再次确认同一提交被拒
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(settings, creds, store, r["submission_id"], {fid: "store"})


async def test_confirm_mode_no_findings_report_locked(settings, maintain_session):
    """确认模式即使无敏感项也生成报告并在确认后锁定。"""
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text="没有任何敏感信息的普通资料", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    rep = db.report_view(r["report_id"])
    assert rep["entries"] == [] and rep["preview"]
    result = await submissions.confirm(settings, creds, store, r["submission_id"], {})
    assert result["task_id"]
    assert db.report_view(r["report_id"])["status"] == "confirmed"


# ---- 报告快照无明文 + 拒绝无副作用 ----

async def test_report_never_contains_plaintext(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text=f"密码 password={SECRET} 身份证 11010519491231002X",
        policy_store=store, knowledge_provider_getter=lambda: FakeProvider(PLAN),
        session_id=maintain_session,
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    decisions = {f["id"]: "store" if f["kind"] == "credential" else "redact" for f in view["findings"]}
    await submissions.confirm(settings, creds, store, r["submission_id"], decisions)
    row = db.get_report(r["report_id"])
    for field in ("entries", "preview", "summary"):
        assert SECRET not in (row[field] or "")
        assert "11010519491231002X" not in (row[field] or "")
    rep = db.report_view(r["report_id"])
    assert SECRET not in json.dumps(rep, ensure_ascii=False)
    # 审计不含原文
    assert SECRET not in json.dumps([dict(e) for e in db.list_security()], ensure_ascii=False)


async def test_reject_no_side_effects(settings, maintain_session):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=maintain_session,
    )
    submissions.cancel(settings, r["submission_id"])
    assert db.report_view(r["report_id"])["status"] == "rejected"
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []


# ---- 多轮维护：同一会话多轮独立报告与任务 ----

async def test_multi_round_maintenance_same_session(settings):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    sid = _new_session(db.SESSION_MAINTAIN)
    r1 = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=sid,
    )
    r2 = await receiver.ingest(
        settings, creds, text="订单服务说明", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN), session_id=sid,
    )
    assert r1["report_id"] != r2["report_id"]
    assert [x["id"] for x in db.list_reports_by_session(sid)] == [r2["report_id"], r1["report_id"]]

    v1 = submissions.view(settings, db.get_submission(r1["submission_id"]))
    fid = v1["findings"][0]["id"]
    res1 = await submissions.confirm(settings, creds, store, r1["submission_id"], {fid: "store"})
    res2 = await submissions.confirm(settings, creds, store, r2["submission_id"], {})
    tasks = [t for t in db.list_tasks() if t["session_id"] == sid]
    assert {t["id"] for t in tasks} == {res1["task_id"], res2["task_id"]}
    assert {t["report_id"] for t in tasks} == {r1["report_id"], r2["report_id"]}


# ---- 前端契约（API 层） ----

def test_session_report_api_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    creds = FakeCredentialStore()
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: creds)
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider(json.dumps({"action": "final", "plan": {
        "source_summary": {"path": "sources/check.md", "title": "来源", "content": "# 来源"},
        "pages": [], "conflicts": [],
    }})))

    with TestClient(main.app) as client:
        a = client.post("/api/chat/sessions", json={"mode": "ask"}).json()
        m = client.post("/api/chat/sessions", json={"mode": "maintain"}).json()
        assert a["mode"] == "ask" and m["mode"] == "maintain"
        sessions = client.get("/api/chat/sessions").json()
        assert {s["session_id"]: s["mode"] for s in sessions}[m["session_id"]] == "maintain"

        client.patch("/api/settings/security", json={"mode": "confirm"})
        bad = client.post("/api/ingest", data={"text": "password=X", "session_id": a["session_id"]})
        assert bad.status_code == 400 and "维护会话" in bad.json()["detail"]

        ing = client.post("/api/ingest", data={"text": f"password={SECRET}", "session_id": m["session_id"]}).json()
        assert ing["pending_confirmation"] is True and ing["report_id"]
        reps = client.get("/api/reports", params={"session_id": m["session_id"]}).json()
        assert len(reps) == 1 and reps[0]["status"] == "pending"

        fid = ing["findings"][0]["id"]
        body = {"decisions": {fid: "store"}, "session_id": m["session_id"]}
        plan = client.post(f"/api/pending/submissions/{ing['submission_id']}/confirm", json=body)
        assert plan.status_code == 202, plan.text
        client.portal.call(main.app.state.ctx.worker.tick)
        conf = plan.json()
        assert conf["task_id"]
        rep = client.get(f"/api/reports/{ing['report_id']}").json()
        assert rep["status"] == "confirmed"

        tasks = client.get("/api/tasks").json()
        t = tasks[0]
        assert t["session_id"] == m["session_id"] and t["report_id"] == ing["report_id"]
        assert SECRET not in json.dumps([rep, tasks], ensure_ascii=False)


# ---- R1 复审回归：报告真正锁定 / 跨 Session 待确认隔离 / duplicate 复扫 ----

def test_report_lock_blocks_content_and_status_change(workspace):
    """报告终态（confirmed/auto/rejected）后任何内容或状态修改都必须被拒且不改原值。"""
    db.create_session("lock-m", db.SESSION_MAINTAIN)
    rid = db.insert_report("lock-m", None, "pending", "confirm", "text", "pasted.txt",
                           "x", "{}", "[]", "safe preview")
    db.update_report(rid, status="confirmed")  # pending → confirmed 允许
    assert db.report_view(rid)["status"] == "confirmed"

    with pytest.raises(ValueError):
        db.update_report(rid, preview="changed after confirmation")
    assert db.get_report(rid)["preview"] == "safe preview"

    with pytest.raises(ValueError):
        db.update_report(rid, status="pending")  # 改回 pending 被拒
    assert db.report_view(rid)["status"] == "confirmed"

    with pytest.raises(ValueError):
        db.update_report(rid, entries='[{"type":"credential"}]')
    assert db.get_report(rid)["entries"] == "[]"


def test_report_lock_auto_and_rejected_are_terminal(workspace):
    db.create_session("lock2", db.SESSION_MAINTAIN)
    r1 = db.insert_report("lock2", None, "pending", "confirm", "text", "pasted.txt",
                          "x", "{}", "[]", "p1")
    db.update_report(r1, status="rejected")
    with pytest.raises(ValueError):
        db.update_report(r1, preview="overwrite")
    assert db.get_report(r1)["preview"] == "p1"

    r2 = db.insert_report("lock2", None, "auto", "auto", "text", "pasted.txt",
                          "x", "{}", "[]", "p2")
    with pytest.raises(ValueError):
        db.update_report(r2, preview="overwrite")
    assert db.get_report(r2)["preview"] == "p2"


async def test_duplicate_confirm_rescan_rejects_unsanitized_preview(settings):
    """duplicate 分支不得绕过复扫：edited_text 含新秘密必须被阻断，报告/载荷不被改写。"""
    store = PolicyStore(settings.policy_file)
    for sid in ("dup-draft", "dup-auto"):
        db.create_session(sid, db.SESSION_MAINTAIN)
    creds = FakeCredentialStore()
    provider = FakeProvider("{}")
    store.update_security_settings({"mode": "confirm"})
    draft = await receiver.ingest(
        settings, creds, text="ordinary duplicate audit text", session_id="dup-draft",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    store.update_security_settings({"mode": "default"})
    await receiver.ingest(
        settings, creds, text="ordinary duplicate audit text", session_id="dup-auto",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    secret = "AuditOnlySecret!"
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(
            settings, creds, store, draft["submission_id"], {},
            edited_text="password=" + secret, knowledge_provider_getter=lambda: provider,
        )
    assert secret not in db.get_report(draft["report_id"])["preview"]
    # 复扫失败：报告仍 pending、提交仍 waiting（不锁定、不清载荷）
    assert db.report_view(draft["report_id"])["status"] == "pending"
    assert db.get_submission(draft["submission_id"])["status"] == "waiting"


async def test_identical_input_keeps_session_ownership(settings):
    """相同文本、不同维护会话：各自独立 Submission/Report，不合并、不串会话。"""
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "confirm"})
    for sid in ("iso-a", "iso-b"):
        db.create_session(sid, db.SESSION_MAINTAIN)
    creds = FakeCredentialStore()
    provider = FakeProvider("{}")
    a = await receiver.ingest(
        settings, creds, text="normal audit document", session_id="iso-a",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    b = await receiver.ingest(
        settings, creds, text="normal audit document", session_id="iso-b",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    assert b["session_id"] == "iso-b"
    assert a["submission_id"] != b["submission_id"]
    assert a["report_id"] != b["report_id"]
    assert db.report_view(a["report_id"])["session_id"] == "iso-a"
    assert db.report_view(b["report_id"])["session_id"] == "iso-b"


async def test_same_session_duplicate_idempotent_and_report_link(settings):
    """同一会话重复提交相同内容：幂等返回同一 Submission/Report，且报告链接提交。"""
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "confirm"})
    db.create_session("same-s", db.SESSION_MAINTAIN)
    creds = FakeCredentialStore()
    provider = FakeProvider("{}")
    r1 = await receiver.ingest(
        settings, creds, text="dup text", session_id="same-s",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    r2 = await receiver.ingest(
        settings, creds, text="dup text", session_id="same-s",
        policy_store=store, knowledge_provider_getter=lambda: provider,
    )
    assert r1["submission_id"] == r2["submission_id"]
    assert r1["report_id"] == r2["report_id"]
    assert db.get_report(r1["report_id"])["submission_id"] == r1["submission_id"]
