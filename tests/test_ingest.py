import asyncio
import json

import pytest

from app import db
from app.ingest import receiver
from app.security import submissions
from app.security.policy import PolicyStore
from app.worker import Worker
from tests.fakes import FakeCredentialStore, FakeProvider

PLAN = '{"action":"final","plan":' + (
    '{"source_summary": {"title": "s", "path": "sources/s.md", "content": "# s\\n内容"}, '
    '"pages": [{"action": "create", "path": "projects/p.md", "title": "p", "content": "# p\\n内容"}], '
    '"conflicts": []}'
) + '}'


def _store(settings):
    return PolicyStore(settings.policy_file)


def _new_session() -> str:
    import uuid

    sid = uuid.uuid4().hex
    db.create_session(sid, db.SESSION_MAINTAIN)
    return sid


@pytest.fixture(autouse=True)
def _knowledge_model_configured(settings):
    """确认闸门需要 knowledge 模型存在（默认查库）；编译用的 Provider 仍由各测试注入 FakeProvider。"""
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")
    _store(settings).update_security_settings({"mode": "confirm"})


async def test_ingest_secret_flow_with_confirmation(settings):
    creds = FakeCredentialStore()
    text = "生产数据库 password=Sup3rSecret! 用于订单服务。"
    provider = FakeProvider(PLAN)
    r = await receiver.ingest(settings, creds, text=text, knowledge_provider_getter=lambda: provider,
                              session_id=_new_session())
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
    assert "[🔒 password](private:pr_" in raw

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
        session_id=_new_session(),
    )
    assert r["pending_confirmation"] is True
    assert r["summary"]["pii"] == 2
    assert {f["rule"] for f in r["findings"]} == {"email", "mobile_phone_cn"}
    assert all(f["suggested_action"] == "store" for f in r["findings"])


async def test_ingest_duplicate(settings):
    creds = FakeCredentialStore()
    provider = FakeProvider(PLAN)
    _store(settings).update_security_settings({"mode": "default"})
    sid = _new_session()
    r1 = await receiver.ingest(settings, creds, text="同样的内容 A", knowledge_provider_getter=lambda: provider,
                               session_id=sid)
    from tests.fakes import finish_queued
    r1 = await finish_queued(settings, creds, r1)
    r2 = await receiver.ingest(settings, creds, text="同样的内容 A", knowledge_provider_getter=lambda: provider,
                               session_id=sid)
    assert r2["duplicate"] is True
    assert r2["source_id"] == r1["source_id"]
    assert len(db.list_tasks()) == 1


class FailingProvider:
    async def complete(self, *args, **kwargs):
        raise RuntimeError("模型不可用")


async def test_failed_round_resubmit_starts_new_round(settings):
    """失败轮重投：复用来源与 Raw，但每轮另起报告与任务，不再被内容去重拦截。"""
    creds = FakeCredentialStore()
    _store(settings).update_security_settings({"mode": "default"})
    sid = _new_session()
    upload = {"filename": "notes.md", "data": "读书会周二九点半。".encode()}
    first = await receiver.ingest(settings, creds, instruction="请整理为项目页。",
                                  knowledge_provider_getter=lambda: FakeProvider(PLAN),
                                  session_id=sid, **upload)
    worker = Worker(settings, creds, lambda: FailingProvider())
    await worker.tick()
    assert db.get_task(first["task_id"])["status"] == "failed"

    second = await receiver.ingest(settings, creds, instruction="请重新整理为概念页。",
                                   knowledge_provider_getter=lambda: FakeProvider(PLAN),
                                   session_id=sid, **upload)
    assert second.get("duplicate") is not True
    assert not db.list_sources()  # 失败轮不留下来源或原件。
    assert second["task_id"] != first["task_id"]
    from tests.fakes import finish_queued
    second = await finish_queued(settings, creds, second)
    assert len(db.list_tasks()) == 2 and len(db.list_reports()) == 2
    assert db.get_source(second["source_id"])["instruction"] == "请重新整理为概念页。"


async def test_failed_round_resubmit_confirm_mode_creates_new_submission(settings):
    """确认模式下失败重投：允许新建提交，确认后复用来源并另起任务。"""
    creds = FakeCredentialStore()
    sid = _new_session()
    upload = {"filename": "notes.md", "data": "读书会周二九点半。".encode()}
    kw = {"knowledge_provider_getter": lambda: FakeProvider(PLAN), "session_id": sid, **upload}
    first = await receiver.ingest(settings, creds, instruction="请整理为项目页。", **kw)
    assert first["pending_confirmation"] is True
    r1 = await submissions.confirm(settings, creds, _store(settings), first["submission_id"], {})
    worker = Worker(settings, creds, lambda: FailingProvider())
    await worker.run_task(r1["task_id"])
    assert db.get_task(r1["task_id"])["status"] == "failed"

    second = await receiver.ingest(settings, creds, instruction="请重新整理为概念页。", **kw)
    assert second["pending_confirmation"] is True
    assert second["submission_id"] != first["submission_id"]
    r2 = await submissions.confirm(settings, creds, _store(settings), second["submission_id"], {})
    assert r2.get("duplicate") is not True
    assert r2["source_id"] == r1["source_id"]
    assert len(db.list_sources()) == 1
    assert len(db.list_tasks()) == 2


async def test_ingest_vault_down_pending_queue(settings):
    creds = FakeCredentialStore(fail=True)
    r = await receiver.ingest(
        settings, creds, text="password=Sup3rSecret!", knowledge_provider_getter=lambda: FakeProvider(PLAN),
        session_id=_new_session(),
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


@pytest.mark.parametrize('extension', ['xlsx', 'xls', 'docx', 'pdf', 'csv'])
@pytest.mark.parametrize('mode', ['confirm', 'default'])
async def test_document_formats_share_security_pipeline(settings, extension, mode):
    from tests.document_samples import sample_file

    creds = FakeCredentialStore()
    provider = FakeProvider(PLAN)
    _store(settings).update_security_settings({'mode': mode})
    result = await receiver.ingest(
        settings, creds, filename=f'资料.{extension}', data=sample_file(extension),
        session_id=_new_session(), knowledge_provider_getter=lambda: provider,
    )
    if mode == 'confirm':
        assert result['pending_confirmation'] is True
        assert creds.created == [] and db.list_tasks() == [] and provider.calls == []
        assert not list(settings.inbox_dir.glob('*'))
        view = submissions.view(settings, db.get_submission(result['submission_id']))
        assert 'DocImport9!' not in json.dumps(view, ensure_ascii=False)
        decisions = {f['id']: 'store' for f in view['findings']}
        assert decisions
        result = await submissions.confirm(settings, creds, _store(settings), result['submission_id'], decisions)
    if mode == 'default':
        await Worker(settings, creds, lambda: provider).tick()
    assert any(item.value == 'DocImport9!' for item in creds.created)
    raw = next(settings.inbox_dir.glob('*')).read_text()
    assert 'DocImport9!' not in raw
    assert 'private:pr_' in raw
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(result['task_id'])
    assert db.get_task(result['task_id'])['status'] == 'done'
    assert (settings.wiki_dir / 'projects/p.md').exists()
    assert provider.calls
    assert 'DocImport9!' not in json.dumps(provider.calls, ensure_ascii=False)
