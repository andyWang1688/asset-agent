from app import db
from app.query import service
from tests.fakes import FakeProvider

import pytest


def _write_page(settings, path, title, content):
    page = settings.wiki_dir / path
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# {title}\n{content}\n", encoding="utf-8")


async def test_answer_with_citations_and_sanitize(settings):
    _write_page(settings, "projects/demo.md", "Demo", "Demo 项目介绍，包含订单服务。")
    provider = FakeProvider("根据 [[projects/demo.md|Demo]]：密码是 sk-proj-abcdEFGH12345678901234567890")
    r = await service.answer(settings, provider, "Demo 项目是什么")
    assert "[[projects/demo.md|Demo]]" in r["answer"]
    assert "sk-proj" not in r["answer"]
    assert r["citations"] == ["projects/demo.md"]
    chats = db.list_chat()
    assert chats[0]["answer"] == r["answer"]
    assert any(e["kind"] == "llm_output_secret" for e in db.list_security())


async def test_answer_empty_wiki(settings):
    provider = FakeProvider("不应被调用")
    r = await service.answer(settings, provider, "没有内容的问题")
    assert "未找到" in r["answer"]
    assert provider.calls == []


async def test_answer_blocks_credentials_in_question(settings):
    provider = FakeProvider("不应被调用")
    with pytest.raises(ValueError) as ei:
        await service.answer(settings, provider, "password=Sup3rSecret! 是什么")
    assert "阻止发送" in str(ei.value)
    assert provider.calls == []  # 秘密原文未进入云端请求
    assert any(e["kind"] == "query_blocked" for e in db.list_security())


async def test_answer_redacts_pii_in_question(settings):
    """PII 仅脱敏：身份证/银行卡进入云端与历史记录前被脱敏。"""
    _write_page(settings, "projects/demo.md", "Demo", "Demo 项目介绍。")
    provider = FakeProvider("根据 [[projects/demo.md|Demo]]：说明。")
    r = await service.answer(settings, provider, "Demo 项目 身份证 11010519491231002X 是什么格式")
    sent = str(provider.calls)
    assert "11010519491231002X" not in sent
    assert "[REDACTED:id_card]" in sent
    chats = db.list_chat()
    assert "11010519491231002X" not in chats[0]["question"]
    assert any(e["kind"] == "query_redacted" for e in db.list_security())


async def test_answer_redacts_email_and_mobile_in_question(settings):
    _write_page(settings, "projects/demo.md", "Demo", "Demo 项目介绍。")
    provider = FakeProvider("根据 [[projects/demo.md|Demo]]：说明。")
    await service.answer(settings, provider, "Demo 联系 user@example.com 或 13812345678")
    sent = str(provider.calls)
    assert "user@example.com" not in sent
    assert "13812345678" not in sent
    assert "[REDACTED:email]" in sent
    assert "[REDACTED:mobile_phone_cn]" in sent
