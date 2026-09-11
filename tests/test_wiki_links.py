"""Wiki 链接目标免检回归：只豁免已验证的真实页面/待写页面路径，标签与正文仍扫描。

等价于控制代理外部用例 /private/tmp/test_assetagent_wiki_links_review.py，并额外守护
“未知路径不得豁免”的边界。"""
import json

import pytest

from app import db
from app.query import index as file_index
from app.query import service
from app.security.policy import PolicyStore
from app.wiki import compiler
from app.wiki.tools import WikiTools

SOURCE = "sources/2026-09-08-blue-whale-reading.md"
PROJECT = "projects/blue-whale-reading.md"


def _create_linked_pages(settings):
    plan = {
        "source_summary": {"path": SOURCE, "title": "来源", "content": f"# 来源\n[[{PROJECT}|蓝鲸读书项目]]"},
        "pages": [
            {
                "action": "create",
                "path": PROJECT,
                "title": "蓝鲸读书项目",
                "content": f"# 蓝鲸读书项目\n来源：[[{SOURCE}|来源]]\n每周二09:30开始。",
            }
        ],
    }
    compiler.apply_plan(settings, plan, 1)


def test_compiled_wiki_preserves_valid_new_page_cross_links(settings):
    _create_linked_pages(settings)
    assert f"[[{PROJECT}|蓝鲸读书项目]]" in (settings.wiki_dir / SOURCE).read_text()
    assert f"[[{SOURCE}|来源]]" in (settings.wiki_dir / PROJECT).read_text()


def test_navigation_and_page_tools_preserve_registered_paths(settings):
    # 直接写入已知安全文件，独立于编译链路验证读取。
    (settings.wiki_dir / SOURCE).write_text(f"# 来源\n[[{PROJECT}|项目]]")
    (settings.wiki_dir / PROJECT).write_text(f"# 项目\n[[{SOURCE}|来源]]")
    compiler.rebuild_index(settings)
    tools = WikiTools(settings)
    assert PROJECT in tools.read_index()["content"]
    assert f"[[{SOURCE}|来源]]" in tools.read_page(PROJECT)["content"]
    index = file_index.load(settings)
    p = next(p for p in index["pages"] if p["path"] == PROJECT)
    assert SOURCE in p["content"]


@pytest.mark.asyncio
async def test_answer_preserves_verified_wiki_links(settings):
    (settings.wiki_dir / PROJECT).write_text("# 项目\n每周二09:30开始。")

    class ReadAndAnswer:
        def __init__(self):
            self.step = 0

        async def complete(self, *args, **kwargs):
            self.step += 1
            return json.dumps(
                {"action": "read", "path": PROJECT} if self.step == 1
                else {"action": "final", "answer": f"每周二09:30开始，见[[{PROJECT}|项目]]。", "citations": [PROJECT]}
            )

    db.create_session("link-question", db.SESSION_ASK)
    answer = await service.answer(settings, ReadAndAnswer(), "何时开始？", session_id="link-question")
    assert f"[[{PROJECT}|项目]]" in answer["answer"]


def test_trusting_link_destination_never_exempts_sensitive_caption(settings):
    (settings.wiki_dir / PROJECT).write_text("# 项目")
    secret = "CaptionFixtureSecret42!"
    (settings.wiki_dir / SOURCE).write_text(f"# 来源\n[[{PROJECT}|password={secret}]]")
    assert secret not in WikiTools(settings).read_page(SOURCE)["content"]


def test_unverified_link_target_is_not_exempted(settings):
    # 未知/未登记为真实文件或待写页面的路径不得豁免：高熵路径仍被安全替换，不成可点击链接。
    (settings.wiki_dir / SOURCE).write_text(f"# 来源\n[[{PROJECT}|项目]]")
    assert PROJECT not in WikiTools(settings).read_page(SOURCE)["content"]


def test_compiled_link_caption_honors_user_regex(settings):
    # 链接目标豁免不关闭自定义规则：标签里的用户正则命中仍须脱敏。
    PolicyStore(settings.policy_file).add_custom_rule(
        {"name": "caption_pin", "pattern": r"LOCAL-PIN:\d{4}", "kind": "credential"}
    )
    (settings.wiki_dir / PROJECT).write_text("# 项目")
    secret = "LOCAL-PIN:4826"
    plan = {"source_summary": {"path": SOURCE, "title": "来源", "content": f"# 来源\n[[{PROJECT}|{secret}]]"}}
    compiler.apply_plan(settings, plan, 1)
    assert secret not in (settings.wiki_dir / SOURCE).read_text()


@pytest.mark.asyncio
async def test_answer_link_caption_honors_user_regex(settings):
    PolicyStore(settings.policy_file).add_custom_rule(
        {"name": "caption_pin", "pattern": r"LOCAL-PIN:\d{4}", "kind": "credential"}
    )
    (settings.wiki_dir / PROJECT).write_text("# 项目")
    secret = "LOCAL-PIN:4826"

    class AnswerEngine:
        async def answer(self, *args, **kwargs):
            return {"answer": f"[[{PROJECT}|{secret}]]", "citations": [PROJECT], "read_pages": [PROJECT]}

    db.create_session("custom-link-question", db.SESSION_ASK)
    result = await service.answer(settings, None, "Question", session_id="custom-link-question", engine=AnswerEngine())
    assert secret not in result["answer"]
