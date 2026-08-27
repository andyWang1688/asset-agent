"""明文与失败处理测试：秘密原文不得进入 Raw/SQLite/审计/错误信息/Wiki/云端请求。"""
import json
import sqlite3

import pytest

from app import db
from app.ingest import receiver
from app.ingest.finalize import finalize
from app.security import submissions
from app.security.detectors import DetectorError
from app.security.policy import PolicyStore
from app.worker import Worker
from tests.fakes import FakeCredentialStore, FakeProvider

SECRET = "Sup3rSecret!"
PLAN = (
    '{"source_summary": {"title": "s", "path": "sources/s.md", "content": "# s\\n内容"}, '
    '"pages": [{"action": "create", "path": "projects/p.md", "title": "p", "content": "# p\\n内容"}], '
    '"conflicts": []}'
)


def _store(settings):
    return PolicyStore(settings.policy_file)


@pytest.fixture(autouse=True)
def _knowledge_model_configured(workspace):
    """确认闸门需要 knowledge 模型存在（默认查库）；编译用的 Provider 仍由各测试注入 FakeProvider。"""
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


async def _ingest_and_confirm(settings, creds, text, decisions_override=None):
    r = await receiver.ingest(
        settings, creds, text=text, policy_store=_store(settings),
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )
    if "pending_confirmation" not in r:
        return r
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    decisions = {f["id"]: (decisions_override or {}).get(f["rule"], f["suggested_action"]) for f in view["findings"]}
    return await submissions.confirm(settings, creds, _store(settings), r["submission_id"], decisions)


async def test_mock_llm_never_receives_plaintext(settings):
    creds = FakeCredentialStore()
    r = await _ingest_and_confirm(
        settings, creds,
        "数据库 password=Sup3rSecret! 订单服务说明\npostgres://user:pass1234@10.0.0.8:5432/db\n"
        "身份证 11010519491231002X\n银行卡 4111111111111111\n",
    )
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(r["task_id"])
    assert db.get_task(r["task_id"])["status"] == "done"
    sent = json.dumps(provider.calls, ensure_ascii=False)
    assert SECRET not in sent
    assert "pass1234" not in sent
    assert "11010519491231002X" not in sent
    assert "4111111111111111" not in sent
    # 脱敏占位符进入了请求
    assert "[SECRET_REF:password]" in sent


async def test_plaintext_not_in_raw_sqlite_audit_wiki(settings):
    creds = FakeCredentialStore()
    r = await _ingest_and_confirm(settings, creds, f"密码 password={SECRET} 与普通内容")
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(r["task_id"])
    assert db.get_task(r["task_id"])["status"] == "done"

    # 1) Raw 文件
    for f in settings.inbox_dir.glob("*"):
        assert SECRET not in f.read_text(encoding="utf-8")
    # 2) Wiki 全部产物
    for f in settings.wiki_dir.rglob("*.md"):
        assert SECRET not in f.read_text(encoding="utf-8")
    # 3) 审计日志
    for e in db.list_security():
        assert SECRET not in json.dumps(dict(e), ensure_ascii=False)
    # 4) SQLite 全库（所有表所有列）
    conn = sqlite3.connect(str(settings.data_dir / "app.db"))
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        try:
            rows = conn.execute(f"SELECT * FROM {name}").fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            assert SECRET not in json.dumps(row, ensure_ascii=False, default=str)
    conn.close()
    # 5) 任务错误信息
    for t in db.list_tasks():
        assert SECRET not in (t["error"] or "")


async def test_detector_failure_blocks_and_leaks_nothing(settings, monkeypatch):
    from app.ingest import receiver as receiver_module

    class BrokenEngine:
        def __init__(self, policy=None, on_warning=None, security_provider=None):
            pass

        def scan(self, text):
            raise DetectorError(f"boom: {text[:40]}")  # 异常信息即使包含明文也必须被吞掉

        async def scan_async(self, text):
            return self.scan(text)

    monkeypatch.setattr(receiver_module, "ScanEngine", BrokenEngine)
    creds = FakeCredentialStore()
    with pytest.raises(ValueError) as ei:
        await receiver.ingest(
            settings, creds, text=f"password={SECRET}", policy_store=_store(settings),
            knowledge_provider_getter=lambda: FakeProvider(PLAN),
        )
    assert SECRET not in str(ei.value)  # 错误信息不含原文
    assert "检测器失败" in str(ei.value)
    # 未落盘、未建任务、未写凭证库
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.list_tasks() == []
    assert creds.created == []
    events = [dict(e) for e in db.list_security() if e["kind"] == "detector_failed"]
    assert events and SECRET not in json.dumps(events, ensure_ascii=False)


async def test_vaultwarden_failure_no_cloud_call(settings):
    creds = FakeCredentialStore(fail=True)
    r = await _ingest_and_confirm(settings, creds, f"password={SECRET}")
    assert r["secrets"][0]["saved"] is False
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    for _ in range(3):
        await worker.tick()
    assert provider.calls == []  # Vaultwarden 失败期间绝不调用云端模型
    assert db.get_task(r["task_id"])["status"] == "credential_pending"


async def test_confirm_error_messages_hide_plaintext(settings):
    creds = FakeCredentialStore()
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    r = await receiver.ingest(
        settings, creds, text=f"password={SECRET}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {})
    assert SECRET not in str(ei.value)


async def test_policy_and_audit_contain_no_secret(settings):
    store = _store(settings)
    policy, errors = store.save("gate:\n  confirm_before_llm: always\n# password=Sup3rSecret!\n")
    assert errors  # 策略拒绝保存
    assert not store.path.exists()
