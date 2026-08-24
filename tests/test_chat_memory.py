"""多轮对话记忆：每次请求从 chat_log 水合最近 N 轮问答；chat_log 是唯一持久化事实源。"""
from app import db
from app.config import Settings
from app.query import service
from tests.fakes import FakeProvider


async def test_followup_uses_prior_context(settings):
    db.upsert_page("projects/demo.md", "Demo", "车险怎么报销？需要什么材料：发票与行程单。")
    provider = FakeProvider("报销材料：发票、行程单。")
    await service.answer(settings, provider, "车险怎么报销", session_id="s1")
    await service.answer(settings, provider, "那需要什么材料", session_id="s1")

    prompt = provider.calls[-1]["user"]
    assert "那需要什么材料" in prompt
    assert "车险怎么报销" in prompt  # 前一轮问题进入上下文
    assert "报销材料：发票、行程单。" in prompt  # 前一轮回答进入上下文


async def test_history_read_from_chat_log_no_second_persistence(settings):
    db.upsert_page("projects/demo.md", "Demo", "第三问的答案见 Demo 项目介绍。")
    db.insert_chat("第一问", "第一答", [], "s2")
    db.insert_chat("第二问", "第二答", [], "s2")
    before = len(db.list_chat())
    provider = FakeProvider("回答")
    await service.answer(settings, provider, "第三问", session_id="s2")

    # 引擎上下文里的历史只能来自 chat_log；本轮请求只新增当前这一条记录
    assert len(db.list_chat()) == before + 1
    prompt = provider.calls[-1]["user"]
    assert "第一问" in prompt and "第一答" in prompt
    assert "第二问" in prompt and "第二答" in prompt
    assert "<对话历史>" in prompt


async def test_memory_rounds_configurable(settings, monkeypatch):
    db.upsert_page("projects/demo.md", "Demo", "新问题的答案见 Demo 项目介绍。")
    for i in range(3):
        db.insert_chat(f"问{i}", f"答{i}", [], "s3")
    monkeypatch.setenv("CHAT_MEMORY_ROUNDS", "1")
    provider = FakeProvider("回答")
    await service.answer(Settings(), provider, "新问题", session_id="s3")

    prompt = provider.calls[-1]["user"]
    assert "问2" in prompt and "答2" in prompt
    assert "问0" not in prompt and "问1" not in prompt


async def test_memory_rounds_default(settings, monkeypatch):
    monkeypatch.delenv("CHAT_MEMORY_ROUNDS", raising=False)
    s = Settings()
    assert s.chat_memory_rounds == 6
    db.upsert_page("projects/demo.md", "Demo", "新问题的答案见 Demo 项目介绍。")
    for i in range(6):
        db.insert_chat(f"问{i}", f"答{i}", [], "s4")
    provider = FakeProvider("回答")
    await service.answer(s, provider, "新问题", session_id="s4")
    assert "问0" in provider.calls[-1]["user"]


async def test_memory_disabled_at_zero_rounds(settings, monkeypatch):
    db.upsert_page("projects/demo.md", "Demo", "新问题的答案见 Demo 项目介绍。")
    db.insert_chat("旧问", "旧答", [], "s5")
    monkeypatch.setenv("CHAT_MEMORY_ROUNDS", "0")
    provider = FakeProvider("回答")
    await service.answer(Settings(), provider, "新问题", session_id="s5")
    assert "旧问" not in provider.calls[-1]["user"]


async def test_session_delete_removes_memory(settings):
    db.upsert_page("projects/demo.md", "Demo", "新问题的答案见 Demo 项目介绍。")
    db.insert_chat("旧问", "旧答", [], "s6")
    db.delete_session("s6")
    provider = FakeProvider("回答")
    await service.answer(settings, provider, "新问题", session_id="s6")
    assert "旧问" not in provider.calls[-1]["user"]


async def test_no_session_no_history(settings):
    db.upsert_page("projects/demo.md", "Demo", "新问题的答案见 Demo 项目介绍。")
    db.insert_chat("旧问", "旧答", [], None)
    provider = FakeProvider("回答")
    await service.answer(settings, provider, "新问题")
    assert "旧问" not in provider.calls[-1]["user"]
