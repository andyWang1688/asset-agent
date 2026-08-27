"""确认闸门测试：等待确认状态、逐项裁决、重新扫描、取消、Vaultwarden 失败挂起、过期、幂等、闸门模式。"""
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
def _knowledge_model_configured(workspace):
    """确认闸门需要 knowledge 模型存在（默认查库）；编译用的 Provider 仍由各测试注入 FakeProvider。"""
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


async def _submit(settings, creds, text):
    store = _store(settings)
    store.update_security_settings({"mode": "confirm"})
    return await receiver.ingest(
        settings, creds, text=text, policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )


async def test_confirmation_state_before_any_side_effect(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret! 说明文字")
    assert r["pending_confirmation"] is True
    sid = r["submission_id"]
    assert db.get_submission(sid)["status"] == "waiting"
    # 等待确认期间：Raw 空、无任务、凭证库无写入、无明文入库
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.list_tasks() == []
    assert creds.created == []
    # 密文队列不含明文
    assert "Sup3rSecret!" not in db.get_submission(sid)["payload"]


async def test_confirm_store_redact_allow(settings):
    creds = FakeCredentialStore()
    text = (
        "密码 password=Sup3rSecret!\n"
        "身份证 11010519491231002X\n"
        "误报字符串 X9kQm2vR7pT3sL8wN4\n"
    )
    r = await _submit(settings, creds, text)
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    by_rule = {f["rule"]: f for f in view["findings"]}
    decisions = {
        by_rule["key_value_secret"]["id"]: "store",
        by_rule["id_card"]["id"]: "redact",
        by_rule["entropy_token"]["id"]: "allow",
    }
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], decisions)
    assert result["secrets_count"] == 1 and result["secrets"][0]["saved"] is True
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "Sup3rSecret!" not in raw
    assert "[SECRET_REF:password]" in raw
    assert "11010519491231002X" not in raw
    assert "[REDACTED:id_card]" in raw
    assert "X9kQm2vR7pT3sL8wN4" in raw  # 误报放行保留原文
    assert creds.created[0].value == "Sup3rSecret!"
    # 放行区间已登记
    src = db.get_source(result["source_id"])
    assert json.loads(src["allowed_spans"]) != []
    # 审计写入且不含原文
    events = [dict(e) for e in db.list_security() if e["kind"] == "finding_decision"]
    assert len(events) == 3
    assert "Sup3rSecret!" not in json.dumps(events, ensure_ascii=False)
    # 任务可编译
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(result["task_id"])
    assert db.get_task(result["task_id"])["status"] == "done"
    assert "Sup3rSecret!" not in json.dumps(provider.calls, ensure_ascii=False)


async def test_confirm_missing_decision_rejected(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    provider = FakeProvider(PLAN)
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {})
    assert "未处置" in str(ei.value)
    # 未调用云端、未写凭证库、未落盘；提交保持等待
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.get_submission(r["submission_id"])["status"] == "waiting"


async def test_confirm_unknown_finding_id_rejected(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(
            settings, creds, _store(settings), r["submission_id"], {fid: "store", "ghost": "store"}
        )


async def test_pii_store_action_rejected(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "身份证 11010519491231002X")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    assert view["findings"][0]["kind"] == "pii"
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert "不允许动作" in str(ei.value)
    assert creds.created == []


async def test_view_masked_context_never_leaks_plaintext(settings):
    """确认视图的掩码上下文不得包含任何 Finding 原文（含部分重叠的窗口边界情况）。"""
    creds = FakeCredentialStore()
    text = "订单服务数据库 password=E2eS3cret! 连接串 postgres://u:p@h:1/d 身份证 11010519491231002X。"
    r = await _submit(settings, creds, text)
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    serialized = json.dumps(view, ensure_ascii=False)
    assert "E2eS3cret!" not in serialized
    assert "11010519491231002X" not in serialized
    # 部分重叠窗口：pii 的上下文窗口伸入前一个凭证 span 时也必须掩码
    pii = next(f for f in view["findings"] if f["kind"] == "pii")
    assert "E2eS3cret" not in pii["context"]
    assert "已掩码" in pii["context"]


async def test_view_context_masks_repeated_value_outside_span(settings):
    """同一秘密值在 Finding span 之外重复出现（未独立命中）也必须掩码。"""
    creds = FakeCredentialStore()
    text = "密码 password=Sup3rSecret! 再次出现 Sup3rSecret! 结尾"
    r = await _submit(settings, creds, text)
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    serialized = json.dumps(view, ensure_ascii=False)
    assert "Sup3rSecret!" not in serialized
    finding = view["findings"][0]
    assert "Sup3rSecret" not in finding["context"]
    assert "Sup3rSecret!" not in view["preview"]


async def test_view_context_short_symbol_value_masked_plain_word_not(settings):
    """兜底阈值：含符号/高熵的 4~7 字符短值在其他位置出现时掩码；普通短词不误掩。"""
    creds = FakeCredentialStore()
    text = "甲 password=ab1! 再来 ab1! 结束"
    r = await _submit(settings, creds, text)
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    serialized = json.dumps(view, ensure_ascii=False)
    assert "ab1!" not in serialized  # 含符号短值兜底掩码
    assert view["findings"][0]["context"].count("已掩码") >= 2


async def test_confirm_edited_preview_accepted(settings):
    """就地修改脱敏预览：合法修改（无敏感内容）→ 落盘采用修改后文本。"""
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret! 说明")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    edited = view["preview"] + "\n（补充说明）"
    result = await submissions.confirm(
        settings, creds, _store(settings), r["submission_id"], {fid: "store"}, edited_text=edited
    )
    assert result["secrets"][0]["saved"] is True
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "（补充说明）" in raw
    assert "Sup3rSecret!" not in raw


async def test_confirm_edited_preview_reintroduced_secret_rejected(settings):
    """修改后重新扫描：编辑内容重新引入秘密 → 阻断，不落盘、不写凭证、不建任务。"""
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(
            settings, creds, _store(settings), r["submission_id"], {fid: "store"},
            edited_text="恶意内容 password=LeakedSecret99!",
        )
    assert "未处置" in str(ei.value)
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.get_submission(r["submission_id"])["status"] == "waiting"  # 可重新裁决


async def test_confirm_edited_preview_keeps_allow_span(settings):
    """编辑后的复扫放行“误报放行”区间（值保留在编辑文本中）。"""
    creds = FakeCredentialStore()
    text = "X9kQm2vR7pT3sL8wN4 与 password=Sup3rSecret!"  # 熵 token 远离关键词 → unknown_suspect
    r = await _submit(settings, creds, text)
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    by_rule = {f["rule"]: f for f in view["findings"]}
    decisions = {
        by_rule["key_value_secret"]["id"]: "store",
        by_rule["entropy_token"]["id"]: "allow",
    }
    edited = "X9kQm2vR7pT3sL8wN4 与 [SECRET_REF:password]（编辑过）"
    result = await submissions.confirm(
        settings, creds, _store(settings), r["submission_id"], decisions, edited_text=edited
    )
    assert result["secrets_count"] == 1
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "X9kQm2vR7pT3sL8wN4" in raw  # 放行区间保留
    assert "Sup3rSecret!" not in raw


async def test_concurrent_confirm_creates_credential_once(settings):
    """并发确认同一提交：进程内互斥保证 Vaultwarden 条目只创建一份。"""
    import asyncio

    class SlowCredentialStore(FakeCredentialStore):
        async def create_secret(self, payload):
            await asyncio.sleep(0.05)  # 拉宽竞态窗口
            return await super().create_secret(payload)

    creds = SlowCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    results = await asyncio.gather(
        submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"}),
        submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"}),
        return_exceptions=True,
    )
    # 恰有一路真正执行（带 task_id）；另一路要么被拒、要么幂等返回 duplicate
    ok = [x for x in results if isinstance(x, dict) and "task_id" in x]
    assert len(ok) == 1
    assert ok[0]["secrets"][0]["saved"] is True
    assert len(creds.created) == 1  # 无重复凭证
    assert len(db.list_tasks()) == 1


async def test_confirm_uses_submission_policy_snapshot(settings, monkeypatch):
    """确认复扫使用提交时策略快照，而非确认时已放宽的当前策略。"""
    creds = FakeCredentialStore()
    store = _store(settings)
    store.save("gate:\n  confirm_before_llm: always\n")
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    store.save("gate:\n  confirm_before_llm: never\n")  # 等待期间策略被放宽

    captured = {}

    class CaptureEngine:
        def __init__(self, policy=None, on_warning=None, security_provider=None):
            captured["policy"] = policy

        def scan(self, text):
            return []

        async def scan_async(self, text):
            return self.scan(text)

    monkeypatch.setattr(submissions, "ScanEngine", CaptureEngine)
    result = await submissions.confirm(settings, creds, store, r["submission_id"], {fid: "store"})
    assert result["secrets"][0]["saved"] is True
    assert captured["policy"]["gate"]["confirm_before_llm"] == "always"  # 快照，而非 never


async def test_cancel_no_writes_and_restore_text(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret! 内容")
    restore = submissions.cancel(settings, r["submission_id"])
    assert "Sup3rSecret!" in restore  # 返回原文供修改后重新提交
    assert db.get_submission(r["submission_id"])["status"] == "cancelled"
    assert db.get_submission(r["submission_id"])["payload"] == ""  # 密文已销毁
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []


async def test_rescan_after_edit_and_resubmit(settings):
    """修改脱敏 → 取消（销毁）→ 修改后重新提交 → 必须重新扫描。"""
    creds = FakeCredentialStore()
    r1 = await _submit(settings, creds, "password=Sup3rSecret!")
    submissions.cancel(settings, r1["submission_id"])
    # 修改后的内容仍含秘密 → 重新扫描后再次进入闸门（而非直通）
    r2 = await _submit(settings, creds, "修改后 password=Sup3rSecret! 仍有密码")
    assert r2["pending_confirmation"] is True
    view = submissions.view(settings, db.get_submission(r2["submission_id"]))
    assert any(f["rule"] == "key_value_secret" for f in view["findings"])
    # 确认模式下，修改后不含秘密也必须再次确认
    r3 = await _submit(settings, creds, "修改后的内容已无敏感信息")
    assert r3["pending_confirmation"] is True
    assert r3["summary"] == {"credential": 0, "pii": 0, "unknown_suspect": 0}


async def test_leftover_after_decisions_rejected(settings, monkeypatch):
    """确认时复扫发现未处置内容 → 阻断，不落盘不发送。"""
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret! 其它内容")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]

    from app.security.detectors import ScanEngine as RealEngine

    class EvilEngine:
        def __init__(self, policy=None, on_warning=None, security_provider=None):
            pass

        def scan(self, text):
            return RealEngine().scan("password=LeakedSecondSecret!")  # 模拟修改后重新扫描出新 Finding

        async def scan_async(self, text):
            return self.scan(text)

    monkeypatch.setattr(submissions, "ScanEngine", EvilEngine)
    with pytest.raises(submissions.SubmissionError) as ei:
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert "未处置" in str(ei.value)
    assert creds.created == []
    assert db.list_tasks() == []
    assert list(settings.inbox_dir.glob("*")) == []


async def test_vaultwarden_failure_pends_task_no_cloud(settings):
    creds = FakeCredentialStore(fail=True)
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert result["secrets"][0]["saved"] is False
    task_id = result["task_id"]
    assert db.get_task(task_id)["status"] == "credential_pending"
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(task_id)
    assert provider.calls == []  # Vaultwarden 失败：任务挂起，不调用云端模型
    # 恢复后补齐并完成
    creds.fail = False
    await worker._flush_pending()
    await worker.run_task(task_id)
    assert db.get_task(task_id)["status"] == "done"


async def test_expire_submission_ttl(settings):
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    settings.queue_ttl_seconds = 0
    worker = Worker(settings, creds, lambda: FakeProvider(PLAN))
    await worker._expire_submissions()
    row = db.get_submission(r["submission_id"])
    assert row["status"] == "expired"
    assert row["payload"] == ""
    assert any(e["kind"] == "submission_expired" for e in db.list_security())
    # 过期后不可确认
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {})


async def test_duplicate_submission_idempotent(settings):
    creds = FakeCredentialStore()
    r1 = await _submit(settings, creds, "password=Sup3rSecret! 内容")
    r2 = await _submit(settings, creds, "password=Sup3rSecret! 内容")
    assert r2["submission_id"] == r1["submission_id"]
    assert len(db.list_submissions("waiting")) == 1
    view = submissions.view(settings, db.get_submission(r1["submission_id"]))
    fid = view["findings"][0]["id"]
    await submissions.confirm(settings, creds, _store(settings), r1["submission_id"], {fid: "store"})
    assert len(creds.created) == 1
    # 已确认后再提交相同内容 → 来源重复，不重复创建凭证/Wiki
    r3 = await _submit(settings, creds, "password=Sup3rSecret! 内容")
    assert r3["duplicate"] is True
    assert len(creds.created) == 1
    assert len(db.list_tasks()) == 1


async def test_resubmit_same_text_after_cancel(settings):
    """取消后重新提交相同内容：允许新建提交（sha256 UNIQUE 冲突已清理），且幂等去重等待态。"""
    creds = FakeCredentialStore()
    r1 = await _submit(settings, creds, "password=Sup3rSecret!")
    submissions.cancel(settings, r1["submission_id"])
    r2 = await _submit(settings, creds, "password=Sup3rSecret!")
    assert r2["pending_confirmation"] is True
    assert r2["submission_id"] != r1["submission_id"]
    assert len(db.list_submissions("waiting")) == 1
    # 重复提交同一等待态内容 → 幂等返回同一提交
    r3 = await _submit(settings, creds, "password=Sup3rSecret!")
    assert r3["submission_id"] == r2["submission_id"]


async def test_confirm_race_duplicate_source_idempotent(settings, monkeypatch):
    """并发确认竞态：落盘阶段发现内容已入库 → 幂等返回既有来源，不重复创建。"""
    creds = FakeCredentialStore()
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]

    from app.ingest import finalize as fm
    from app.security import submissions as sm

    async def fake_finalize(*a, **k):
        raise fm.DuplicateSourceError(42)

    monkeypatch.setattr(sm, "finalize", fake_finalize)
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert result["duplicate"] is True and result["source_id"] == 42
    assert db.get_submission(r["submission_id"])["status"] == "confirmed"
    assert creds.created == []


async def test_claim_rollback_on_rescan_failure(settings, monkeypatch):
    """两阶段落库：占位后复扫失败 → 回滚占位行与待处理凭证，不留残留。"""
    creds = FakeCredentialStore(fail=True)  # 凭证写入进入 pending 队列，验证回滚一并清除
    r = await _submit(settings, creds, "password=Sup3rSecret!")
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    sha = db.get_submission(r["submission_id"])["sha256"]

    from app.security.detectors import ScanEngine as RealEngine

    class EvilEngine:
        def __init__(self, policy=None, on_warning=None, security_provider=None):
            pass

        def scan(self, text):
            return RealEngine().scan("password=Leaked99!")  # 复扫必中

        async def scan_async(self, text):
            return self.scan(text)

    monkeypatch.setattr(submissions, "ScanEngine", EvilEngine)
    with pytest.raises(submissions.SubmissionError):
        await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert db.get_source_by_sha256(sha) is None  # 占位行已回滚
    assert db.list_pending() == []  # 待处理凭证已清除
    assert db.list_tasks() == []
    assert db.get_submission(r["submission_id"])["status"] == "waiting"


async def test_stale_unconfirmed_placeholder_reclaimed(settings):
    """崩溃遗留的 confirmed=0 占位（超过回收时限）在重试时复用，内容不丢失。"""
    creds = FakeCredentialStore()
    text = "回收测试 password=ReclaimSecret!"
    sha = __import__("app.crypto", fromlist=["sha256_hex"]).sha256_hex(text)
    sid = db.insert_source(sha, "text", "pasted.txt", "", "[]", confirmed=0)
    db._w("UPDATE sources SET created_at=? WHERE id=?", ("2020-01-01 00:00:00", sid))

    r = await _submit(settings, creds, text)
    assert r["pending_confirmation"] is True  # ingest 不把未确认占位当重复
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert result["source_id"] == sid  # 复用占位行，不新建
    row = db.get_source(sid)
    assert row["confirmed"] == 1 and row["path"]
    assert len(db.list_tasks()) == 1
    assert creds.created[0].value == "ReclaimSecret!"


async def test_fresh_unconfirmed_placeholder_conflict_returns_duplicate(settings):
    """进行中的 confirmed=0 占位（未超时）：并发确认冲突 → 幂等返回，不新建来源/凭证。"""
    creds = FakeCredentialStore()
    text = "冲突测试 password=ConflictSecret!"
    sha = __import__("app.crypto", fromlist=["sha256_hex"]).sha256_hex(text)
    db.insert_source(sha, "text", "pasted.txt", "", "[]", confirmed=0)  # 刚创建（未超时）

    r = await _submit(settings, creds, text)
    assert r["pending_confirmation"] is True
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    result = await submissions.confirm(settings, creds, _store(settings), r["submission_id"], {fid: "store"})
    assert result["duplicate"] is True
    assert creds.created == []
    assert db.list_tasks() == []


async def test_gate_never_direct_flow(settings):
    store = _store(settings)
    store.save("gate:\n  confirm_before_llm: never\n")
    creds = FakeCredentialStore()
    r = await receiver.ingest(
        settings, creds, text="password=Sup3rSecret!", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )
    assert "pending_confirmation" not in r
    assert r["secrets"][0]["saved"] is True
    raw = next(settings.inbox_dir.glob("*")).read_text(encoding="utf-8")
    assert "Sup3rSecret!" not in raw


async def test_gate_always_plain_text_requires_confirm(settings):
    store = _store(settings)
    store.save("gate:\n  confirm_before_llm: always\n")
    creds = FakeCredentialStore()
    r = await receiver.ingest(
        settings, creds, text="没有任何敏感信息的普通文本", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(PLAN),
    )
    assert r["pending_confirmation"] is True
    assert r["summary"] == {"credential": 0, "pii": 0, "unknown_suspect": 0}
    # 空裁决确认 → 直通
    result = await submissions.confirm(settings, creds, store, r["submission_id"], {})
    assert result["source_id"]
    assert creds.created == []


async def test_worker_blocks_unconfirmed_source(settings):
    creds = FakeCredentialStore()
    src_id = db.insert_source("deadbeef" * 8, "text", "x", "/nonexistent", "[]", confirmed=0)
    task_id = db.insert_task(src_id)
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(task_id)
    assert db.get_task(task_id)["status"] == "failed"
    assert provider.calls == []
    assert any(e["kind"] == "gate_blocked" for e in db.list_security())


async def test_worker_ignores_raw_header_noise(settings):
    """Raw 文件头（长混合文件名/哈希）不得触发编译前复扫误阻断。"""
    creds = FakeCredentialStore()
    long_name = "X9kQm2vR7pT3sL8wN4.txt"  # 高熵文件名会被熵检测误判，但它在文件头
    raw_path = settings.inbox_dir / long_name
    raw_path.write_text(
        f"# 来源: {long_name}\n\n<!-- kind: text, sha256: {'ab' * 32}, ingested_at: 2026-08-18 10:00:00 -->\n\n"
        "这是普通的中文资料内容，不包含任何敏感信息。\n",
        encoding="utf-8",
    )
    src_id = db.insert_source("beef" * 16, "text", long_name, str(raw_path), "[]", confirmed=1, allowed_spans="[]")
    task_id = db.insert_task(src_id)
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(task_id)
    assert db.get_task(task_id)["status"] == "done"
    assert provider.calls  # 文件头噪声不阻断编译


async def test_worker_blocks_leftover_secret_in_raw(settings):
    creds = FakeCredentialStore()
    raw_path = settings.inbox_dir / "evil.txt"
    raw_path.write_text("# 来源: x\n\npassword=Sup3rSecret! 泄漏\n", encoding="utf-8")
    src_id = db.insert_source("cafebabe" * 8, "text", "x", str(raw_path), "[]", confirmed=1, allowed_spans="[]")
    task_id = db.insert_task(src_id)
    provider = FakeProvider(PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(task_id)
    assert db.get_task(task_id)["status"] == "failed"
    assert provider.calls == []


def test_pending_queue_key_file_used(settings, tmp_path, monkeypatch):
    import os

    from app import crypto
    from app.config import Settings

    key = os.urandom(32)
    kf = tmp_path / "queue.key"
    kf.write_bytes(key)
    monkeypatch.setenv("PENDING_QUEUE_KEY_FILE", str(kf))
    s2 = Settings()
    assert s2.queue_key() == key
    # 提交密文只能用队列密钥解开，本地密钥解不开
    row = db.get_submission(submissions.create_submission(
        s2, "password=Sup3rSecret!", [], "aa" * 32, "text", "pasted.txt"))
    assert "Sup3rSecret!" not in row["payload"]
    crypto.open_sealed(key, row["payload"])  # 队列密钥可解
    with pytest.raises(Exception):
        crypto.open_sealed(s2.local_key(), row["payload"])


def test_key_file_with_whitespace_flanked_bytes(settings, tmp_path, monkeypatch):
    """回归：原始 32 字节密钥恰以空白字节开头/结尾时不得被 strip 损坏。"""
    import os

    from app.config import Settings

    key = b"\x20" + os.urandom(30) + b"\x0a"  # 首尾均为空白字节
    kf = tmp_path / "odd.key"
    kf.write_bytes(key)
    monkeypatch.setenv("PENDING_QUEUE_KEY_FILE", str(kf))
    s2 = Settings()
    assert s2.queue_key() == key
    # hex 文本密钥（含换行）仍可解析
    kf.write_bytes(key.hex().encode() + b"\n")
    s3 = Settings()
    assert s3.queue_key() == key


def test_pending_queue_key_falls_back_to_local_key(settings, tmp_path, monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("PENDING_QUEUE_KEY_FILE", str(tmp_path / "missing.key"))
    s2 = Settings()
    assert s2.queue_key() == s2.local_key()


def test_extra_rule_runtime_timeout_degrades_gracefully():
    """自定义规则运行期超时/异常：跳过该规则并回退基础结果，不阻断服务。"""
    from app.security.detectors import ScanEngine
    from app.security.policy import default_policy

    policy = default_policy()
    policy["detection"]["extra_rules"] = [{"name": "re", "pattern": "(a+)+$", "kind": "credential"}]
    warnings = []
    engine = ScanEngine(policy, on_warning=warnings.append)
    findings = engine.scan("password=abc123 说明\n" + "a" * 5000 + "b")
    # 基础规则仍生效；自定义规则被跳过并告警
    assert any(f.rule == "key_value_secret" for f in findings)
    assert any("re" in w for w in warnings)
