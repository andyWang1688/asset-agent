"""LLM Wiki Agent：受限工具循环（read/search/final）驱动的问答与维护。

验证：工具真实执行、引用只来自真正读到的页面、维护先读旧页后更新、越权路径拒绝、
embedding factory 不被主链路调用、任务记录真实变更、秘密不进模型请求。"""
import json

import pytest

from app import db
from app.config import Settings
from app.ingest import receiver
from app.query import service
from app.query.engine import WikiQuestionAnswerEngine
from app.security.policy import PolicyStore
from app.wiki import compiler
from app.wiki.tools import ToolError, WikiTools, _safe_page
from app.worker import Worker
from app.llm.provider import LLMError
from tests.fakes import FakeCredentialStore, FakeProvider, SequenceProvider


def _write_page(settings, path, title, content):
    page = settings.wiki_dir / path
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# {title}\n{content}\n", encoding="utf-8")


def _final(answer, citations=()):
    return json.dumps({"action": "final", "answer": answer, "citations": list(citations)}, ensure_ascii=False)


FINAL_PLAN = json.dumps({"action": "final", "plan": {
    "source_summary": {"title": "s", "path": "sources/s.md", "content": "# s\n内容"},
    "pages": [{"action": "create", "path": "projects/p.md", "title": "p", "content": "# p\n订单服务"}],
    "conflicts": [],
}}, ensure_ascii=False)


# ---- 问答：工具真实执行 + 引用只来自真正读到的页面 ----

async def test_query_reads_page_then_answers(settings):
    _write_page(settings, "projects/demo.md", "Demo", "Demo 项目介绍，包含订单服务。")
    provider = SequenceProvider([
        json.dumps({"action": "read", "path": "projects/demo.md"}),
        _final("根据 [[projects/demo.md|Demo]]：订单服务。", citations=["projects/demo.md"]),
    ])
    r = await service.answer(settings, provider, "订单服务是什么")
    assert r["answer"] == "根据 [[projects/demo.md|Demo]]：订单服务。"
    assert r["citations"] == ["projects/demo.md"]
    # 问答期间 Wiki 内容与任务数不变
    assert db.list_tasks() == []
    assert "Demo 项目介绍" in (settings.wiki_dir / "projects/demo.md").read_text()


async def test_query_citations_only_from_read_pages(settings):
    _write_page(settings, "projects/read.md", "已读", "已读页面内容。")
    _write_page(settings, "projects/notread.md", "未读", "未读页面内容。")
    provider = SequenceProvider([
        json.dumps({"action": "read", "path": "projects/read.md"}),
        _final("回答。", citations=["projects/read.md", "projects/notread.md"]),
    ])
    r = await service.answer(settings, provider, "问题")
    assert r["citations"] == ["projects/read.md"]  # 未读页面被剔除


async def test_query_search_then_answer(settings):
    _write_page(settings, "concepts/orders.md", "订单", "订单服务使用缓存。")
    provider = SequenceProvider([
        json.dumps({"action": "search", "query": "订单"}),
        _final("订单服务使用缓存。", citations=["concepts/orders.md"]),
    ])
    r = await service.answer(settings, provider, "订单缓存")
    assert r["citations"] == ["concepts/orders.md"]


# ---- 维护：先读旧页再更新 ----

async def test_maintain_reads_full_page_before_update(settings):
    _write_page(settings, "projects/demo.md", "Demo", "旧事实：保留这一段，别丢。")
    plan = {"source_summary": {}, "pages": [
        {"action": "update", "path": "projects/demo.md", "title": "Demo",
         "content": "# Demo\n旧事实：保留这一段，别丢。\n新事实。"}
    ], "conflicts": []}
    provider = SequenceProvider([
        json.dumps({"action": "read", "path": "projects/demo.md"}),
        json.dumps({"action": "final", "plan": plan}, ensure_ascii=False),
    ])
    await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    # 第二次调用（final）的 prompt 包含旧页全文（未被 3000 字符截断）
    assert "旧事实：保留这一段，别丢。" in provider.calls[1]["user"]
    assert "旧事实" in (settings.wiki_dir / "projects/demo.md").read_text()


async def test_maintain_task_records_changes(settings, maintain_session):
    creds = FakeCredentialStore()
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "default"})
    r = await receiver.ingest(
        settings, creds, text="订单资料", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(FINAL_PLAN), session_id=maintain_session,
    )
    worker = Worker(settings, creds, lambda: FakeProvider(FINAL_PLAN))
    await worker.run_task(r["task_id"])
    t = db.get_task(r["task_id"])
    assert t["status"] == "done"
    result = json.loads(t["result"])
    assert "projects/p.md" in result["changes"]
    assert "sources/s.md" in result["changes"]


# ---- 越权路径 / 写动作 ----

@pytest.mark.parametrize("bad", [
    "../private-raw/x.md", "/etc/passwd.md", "concepts/../../x.md",
    "..%2fetc.md", "concepts/x.txt", "evil.md", "concepts/a/b.md",
])
def test_safe_page_rejects_escape(settings, bad):
    with pytest.raises(ToolError):
        _safe_page(settings, bad)


def test_safe_page_rejects_symlink_escape(settings):
    outside = settings.workspace_dir / "outside.md"
    outside.write_text("secret")
    link = settings.wiki_dir / "concepts" / "link.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    with pytest.raises(ToolError):
        _safe_page(settings, "concepts/link.md")


async def test_infinite_invalid_actions_fail_without_write(settings):
    """恶意模型一直要求读非法路径：结束失败且不写任何页面。"""
    provider = SequenceProvider([json.dumps({"action": "read", "path": "../../etc/passwd.md"}) for _ in range(10)])
    with pytest.raises(Exception):
        await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    assert list((settings.wiki_dir / "projects").glob("*.md")) == []


async def test_write_action_rejected(settings):
    """工具集只读：模型要求写文件 → 未知动作，最终失败不写。"""
    provider = SequenceProvider([
        json.dumps({"action": "write", "path": "projects/x.md", "content": "bad"}),
        json.dumps({"action": "final", "plan": {}}),
    ])
    await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    assert not (settings.wiki_dir / "projects" / "x.md").exists()


# ---- 主链路不调用 embedding / reranker ----

async def test_default_chain_never_loads_embedding(settings, monkeypatch):
    from app.query import hybrid, retrieval

    def boom(*a, **k):
        raise RuntimeError("embedding should not be called")

    monkeypatch.setattr(hybrid, "build_embedding_provider", boom)
    monkeypatch.setattr(retrieval, "build_embedding_provider", boom)
    _write_page(settings, "projects/demo.md", "Demo", "订单服务。")
    provider = SequenceProvider([_final("订单服务。", citations=["projects/demo.md"])])
    r = await service.answer(settings, provider, "订单服务是什么")
    assert r["answer"] == "订单服务。"


async def test_maintain_rebuild_skips_vector(settings, monkeypatch):
    from app.query import retrieval

    called = []
    monkeypatch.setattr(retrieval, "build", lambda *a, **k: called.append(1))
    provider = FakeProvider(FINAL_PLAN)
    await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    assert called == []


# ---- 秘密不进模型请求 ----

async def test_maintain_prompt_contains_no_secret(settings, maintain_session):
    creds = FakeCredentialStore()
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "default"})
    secret = "Sup3rSecret!"
    r = await receiver.ingest(
        settings, creds, text=f"password={secret}", policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider(FINAL_PLAN), session_id=maintain_session,
    )
    provider = FakeProvider(FINAL_PLAN)
    worker = Worker(settings, creds, lambda: provider)
    await worker.run_task(r["task_id"])
    assert db.get_task(r["task_id"])["status"] == "done"
    assert secret not in json.dumps(provider.calls, ensure_ascii=False)


# ---- R1 回归：读工具脱敏 / 路径与写入越权 / 计划整体校验 / 读取证据 ----

async def test_read_page_does_not_send_new_secret(settings):
    secret = "OnlyFixtureSecret42!"
    _write_page(settings, "entities/fixture.md", "Fixture", f"password={secret}")
    m = SequenceModel(
        {"action": "read", "path": "entities/fixture.md"},
        {"action": "final", "answer": "Safe", "citations": ["entities/fixture.md"]},
    )
    try:
        await WikiQuestionAnswerEngine(settings).answer(m, "Summarize")
    except (ValueError, LLMError, ToolError):
        pass
    assert secret not in json.dumps(m.calls)


def test_read_index_rejects_symlink_escape(settings, tmp_path):
    outside = tmp_path / "outside-fixture.txt"
    outside.write_text("OUTSIDE-FIXTURE")
    idx = settings.wiki_dir / "index.md"
    idx.unlink()
    idx.symlink_to(outside)
    try:
        result = WikiTools(settings).read_index()
    except (ValueError, ToolError):
        return
    assert "OUTSIDE-FIXTURE" not in json.dumps(result)


def test_search_does_not_return_deleted_page(settings):
    from app.query import index as file_index

    p = _write_page(settings, "entities/pineapple.md", "Pineapple", "Pineapple fact.")
    file_index.build(settings)
    (settings.wiki_dir / "entities" / "pineapple.md").unlink()
    assert not WikiTools(settings).search("Pineapple").get("results")


def test_write_plan_does_not_follow_outside_symlink(settings, tmp_path, monkeypatch):
    outside = tmp_path / "outside-fixture.txt"
    outside.write_text("UNTOUCHED")
    (settings.wiki_dir / "entities" / "fixture.md").symlink_to(outside)
    monkeypatch.setattr(compiler, "rebuild_index", lambda *_: None)
    plan = {"pages": [{"action": "update", "path": "entities/fixture.md", "title": "Fixture", "content": "CHANGED"}]}
    try:
        compiler.apply_plan(settings, plan, 1)
    except (ValueError, LLMError, ToolError):
        pass
    assert outside.read_text() == "UNTOUCHED"


def test_validate_whole_plan_before_writing(settings, monkeypatch):
    p = settings.wiki_dir / "entities" / "fixture.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Existing\nOld fact.")
    old = p.read_text()
    monkeypatch.setattr(compiler, "rebuild_index", lambda *_: None)
    plan = {"pages": [
        {"action": "update", "path": "entities/fixture.md", "title": "Fixture", "content": "Changed"},
        {"action": "create", "path": "../outside.md", "title": "Bad", "content": "Bad"},
    ]}
    with pytest.raises((ValueError, LLMError, ToolError)):
        compiler.apply_plan(settings, plan, 1)
    assert p.read_text() == old


async def test_inline_citation_requires_read_page(settings):
    _write_page(settings, "entities/fixture.md", "Fixture", "Ordinary evidence.")
    m = SequenceModel(
        {"action": "read", "path": "entities/fixture.md"},
        {"action": "final", "answer": "See [[entities/missing.md|Invented]]", "citations": ["entities/missing.md"]},
    )
    r = await WikiQuestionAnswerEngine(settings).answer(m, "Question")
    assert "entities/missing.md" not in r["answer"]
    assert "entities/missing.md" not in r["citations"]


async def test_first_model_context_contains_actual_index(settings):
    (settings.wiki_dir / "index.md").write_text("# Index\n索引中的项目入口\n")
    m = SequenceModel({"action": "final", "answer": "No record", "citations": []})
    await WikiQuestionAnswerEngine(settings).answer(m, "Question")
    assert "索引中的项目入口" in m.calls[0]["user"]


async def test_step_budget_forces_final_instead_of_abort(settings):
    """开放式问题反复读取耗尽步数：临近上限提醒收口，用尽后仍给一次只输出 final 的机会。"""
    _write_page(settings, "projects/loop.md", "Loop", "循环测试内容。")
    m = SequenceModel(
        {"action": "read", "path": "projects/loop.md"},
        {"action": "read", "path": "projects/loop.md"},
        {"action": "final", "answer": "基于已读内容。", "citations": ["projects/loop.md"]},
    )
    r = await WikiQuestionAnswerEngine(settings, max_steps=2).answer(m, "介绍下你知道的知识")
    assert r["answer"] == "基于已读内容。"
    assert r["citations"] == ["projects/loop.md"]
    assert "剩余动作步数" in m.calls[0]["user"]
    assert "最后机会" in m.calls[-1]["user"]
    assert len(m.calls) == 3


async def test_step_budget_still_fails_without_final(settings):
    """耗尽步数且最后一次仍不输出 final：必须失败，不返回残缺结果。"""
    _write_page(settings, "projects/loop.md", "Loop", "循环测试内容。")
    m = SequenceModel(
        {"action": "read", "path": "projects/loop.md"},
        {"action": "read", "path": "projects/loop.md"},
        {"action": "read", "path": "projects/loop.md"},
    )
    with pytest.raises(LLMError):
        await WikiQuestionAnswerEngine(settings, max_steps=2).answer(m, "介绍下你知道的知识")


async def test_update_must_read_existing_page(settings, monkeypatch):
    p = settings.wiki_dir / "entities" / "fixture.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Existing\nImportant old fact.")
    old = p.read_text()
    monkeypatch.setattr(compiler, "rebuild_index", lambda *_: None)
    m = SequenceModel({"action": "final", "plan": {"pages": [
        {"action": "update", "path": "entities/fixture.md", "title": "Fixture", "content": "Replacement."}
    ]}})
    try:
        await compiler.compile_source(settings, m, {"id": 1, "instruction": "Add fact"}, "New safe fact")
    except (ValueError, LLMError, ToolError):
        pass
    assert p.read_text() == old


class SequenceModel:
    """按顺序返回 JSON 动作（等价控制代理 fixture，供本仓库回归用）。"""

    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls = []

    async def complete(self, system, user, **kwargs):
        self.calls.append({"system": system, "user": user})
        action = self.actions.pop(0) if self.actions else {"action": "final", "answer": "No further information", "citations": []}
        return json.dumps(action)


# ---- R1 追加：source_summary 读取证据 / 索引预算 / 文件名脱敏 ----

async def test_existing_source_summary_requires_read_evidence(settings, monkeypatch):
    p = settings.wiki_dir / "sources" / "original.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Original\nAn important older fact.")
    old = p.read_text()
    monkeypatch.setattr(compiler, "rebuild_index", lambda *_: None)
    m = SequenceModel({"action": "final", "plan": {"source_summary": {
        "path": "sources/original.md", "title": "Original", "content": "Replacement without reading"
    }}})
    try:
        await compiler.compile_source(settings, m, {"id": 1, "instruction": "Add fact"}, "New safe fact")
    except (ValueError, LLMError, ToolError):
        pass
    assert p.read_text() == old


async def test_initial_index_budget_overflow_fails(settings):
    (settings.wiki_dir / "index.md").write_text("# Index\nOrdinary navigation content.")
    m = SequenceModel({"action": "final", "answer": "Done", "citations": []})
    with pytest.raises((ValueError, LLMError, ToolError)):
        await WikiQuestionAnswerEngine(settings, max_read_chars=4).answer(m, "Question")


async def test_upload_filename_does_not_leak(settings, maintain_session):
    secret = "FilenameFixture99!"
    store = PolicyStore(settings.policy_file)
    store.update_security_settings({"mode": "default"})
    vault = FakeCredentialStore()
    m = SequenceModel({"action": "final", "plan": {"source_summary": {
        "path": "sources/fixture.md", "title": "Fixture", "content": "# Safe summary"
    }}})
    result = await receiver.ingest(
        settings, vault, filename=f"password={secret}.txt", data=b"Ordinary uploaded content.",
        session_id=maintain_session, knowledge_provider_getter=lambda: m,
    )
    worker = Worker(settings, vault, lambda: m, security_provider_getter=lambda: None)
    await worker.run_task(result["task_id"], m)
    assert secret not in json.dumps(m.calls)


# ---- R2 回归：index 真实策略 / 系统文件越权 / list/search 读穿 symlink ----

@pytest.mark.parametrize("secret", ["L8vQw2nZ7pJ4tB6xD9rS", "LOCAL-PIN:4826"])
async def test_index_obeys_entropy_and_custom_policy(settings, secret):
    store = PolicyStore(settings.policy_file)
    store.add_custom_rule({"name": "local_pin", "pattern": r"LOCAL-PIN:\d{4}", "kind": "credential"})
    (settings.wiki_dir / "index.md").write_text("# Index\n" + secret)
    m = SequenceModel({"action": "final", "answer": "Safe", "citations": []})
    try:
        await WikiQuestionAnswerEngine(settings).answer(m, "Question")
    except (ValueError, LLMError, ToolError):
        pass
    assert secret not in json.dumps(m.calls)


@pytest.mark.parametrize("filename", ["index.md", "log.md"])
def test_system_wiki_files_cannot_write_outside_root(settings, tmp_path, filename):
    outside = tmp_path / "system-outside-fixture.txt"
    outside.write_text("UNTOUCHED")
    target = settings.wiki_dir / filename
    target.unlink()
    target.symlink_to(outside)
    plan = {"pages": [{"action": "create", "path": "entities/new.md", "title": "New", "content": "# New\nA safe fact."}]}
    try:
        compiler.apply_plan(settings, plan, 1)
    except (ValueError, LLMError, ToolError):
        pass
    assert outside.read_text() == "UNTOUCHED"


def test_search_and_listing_cannot_read_outside_symlink(settings, tmp_path):
    outside = tmp_path / "private-source.txt"
    outside.write_text("# Pineapple\nPineapple private fact.")
    (settings.wiki_dir / "entities" / "escape.md").symlink_to(outside)
    tools = WikiTools(settings)
    try:
        listing = tools.list_pages()
        result = tools.search("Pineapple")
    except (ValueError, LLMError, ToolError):
        return
    assert "entities/escape.md" not in json.dumps(listing)
    assert not result.get("results")
