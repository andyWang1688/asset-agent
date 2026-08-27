import asyncio
import json

import pytest

from app import db
from app.ingest import receiver
from app.security import submissions
from app.security.policy import PolicyStore
from app.worker import Worker
from tests.fakes import FakeCredentialStore, FakeProvider

PLAN = (
    '{"source_summary": {"title": "s", "path": "sources/s.md", "content": "# s\\n内容"}, '
    '"pages": [{"action": "create", "path": "projects/p.md", "title": "p", "content": "# p\\n内容"}], '
    '"conflicts": []}'
)


def _store(settings):
    return PolicyStore(settings.policy_file)


@pytest.fixture(autouse=True)
def _knowledge_model_configured(settings):
    """确认闸门需要 knowledge 模型存在（默认查库）；编译用的 Provider 仍由各测试注入 FakeProvider。"""
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")
    _store(settings).update_security_settings({"mode": "confirm"})


async def test_ingest_secret_flow_with_confirmation(settings):
    creds = FakeCredentialStore()
    text = "生产数据库 password=Sup3rSecret! 用于订单服务。"
    provider = FakeProvider(PLAN)
    r = await receiver.ingest(settings, creds, text=text, knowledge_provider_getter=lambda: provider)
    assert r["pending_confirmation"] is True
    assert r["summary"]["credential"] == 1
    # 确认前：不落盘、不建任务、不写凭证库、不调模型
    assert not list(settings.inbox_dir.glob("*"))
    assert db.list_tasks() == []
    assert creds.created == []

    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    assert "Sup3rSecret!" not in json.dumps(view)  # 视图绝不含原文
    finding = view["findings"][0]
    assert finding["kind"] == "credential"
    assert finding["suggested_action"] == "store"

    result = await submissions.confirm(
        settings, creds, _store(settings), r["submission_id"], {finding["id"]: "store"}
    )
    assert result["secrets"][0]["saved"] is True
    assert creds.created[0].value == "Sup3rSecret!"
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "Sup3rSecret!" not in raw
    assert "[SECRET_REF:password]" in raw

    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(result["task_id"])
    assert db.get_task(result["task_id"])["status"] == "done"
    assert (settings.wiki_dir / "projects/p.md").exists()
    # 秘密原文未进入云端请求
    assert all("Sup3rSecret!" not in json.dumps(c, ensure_ascii=False) for c in provider.calls)


async def test_ingest_pii_enters_confirmation_gate(settings):
    r = await receiver.ingest(
        settings,
        FakeCredentialStore(),
        text="联系人 user@example.com，手机 13812345678。",
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )
    assert r["pending_confirmation"] is True
    assert r["summary"]["pii"] == 2
    assert {f["rule"] for f in r["findings"]} == {"email", "mobile_phone_cn"}
    assert all(f["suggested_action"] == "redact" for f in r["findings"])


async def test_ingest_duplicate(settings):
    creds = FakeCredentialStore()
    provider = FakeProvider(PLAN)
    _store(settings).update_security_settings({"mode": "default"})
    r1 = await receiver.ingest(settings, creds, text="同样的内容 A", knowledge_provider_getter=lambda: provider)
    r2 = await receiver.ingest(settings, creds, text="同样的内容 A", knowledge_provider_getter=lambda: provider)
    assert r2["duplicate"] is True
    assert r2["source_id"] == r1["source_id"]
    assert len(db.list_tasks()) == 1


async def test_ingest_vault_down_pending_queue(settings):
    creds = FakeCredentialStore(fail=True)
    r = await receiver.ingest(
        settings, creds, text="password=Sup3rSecret!", knowledge_provider_getter=lambda: FakeProvider(PLAN)
    )
    assert r["pending_confirmation"] is True
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    # Vaultwarden 失败：任务挂起，不调用云端模型
    assert result["secrets"][0]["saved"] is False
    assert db.get_task(result["task_id"])["status"] == "credential_pending"
    pending = db.list_pending("pending")
    assert len(pending) == 1
    # 队列密文中不含明文
    assert "Sup3rSecret!" not in pending[0]["payload"]
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(result["task_id"])
    assert provider.calls == []  # 凭证未补齐前绝不调用云端
    # 恢复后 worker 补齐并完成任务
    creds.fail = False
    await worker._flush_pending()
    await worker.run_task(result["task_id"])
    assert db.get_task(result["task_id"])["status"] == "done"
    assert creds.created[0].value == "Sup3rSecret!"
    assert db.list_pending("pending") == []
