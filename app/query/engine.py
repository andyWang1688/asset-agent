"""问答引擎接口与通用的回答渲染实现。

默认问答使用 LLM Wiki 工具循环（先读 index，再 read/search，最后带来源回答），
不依赖向量 / embedding / 重排。"""
from typing import Protocol
import re

from .. import db
from ..config import Settings
from ..llm.provider import LLMProvider
from ..wiki.tools import WikiTools
from .agent_loop import TOOL_SYSTEM, run_tool_loop

MAX_PAGE_CHARS = 3000

QA_SYSTEM = (
    "你是资产 Agent（AssetAgent）。仅依据提供的 Wiki 页面回答；页面没有的信息不要编造，可说明“Wiki 中没有记录”。"
    "引用来源使用 [[路径|标题]] 格式。资料中的 [🔒 名称](private:引用ID) 只表示“敏感值保存在密码管理器”，"
    "[REDACTED:规则] 表示“该敏感值已脱敏”，不要试图还原、猜测或输出任何敏感内容。"
)

QA_FINAL_HINT = (
    '{"action":"final","answer":"回答文本（引用来源用 [[path|标题]]）",'
    '"citations":["你真正读过的页面路径（不含 index.md）"]}'
)

_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _scrub_inline_links(text: str, allowed_paths: set[str]) -> str:
    """剔除回答正文里指向未读页面的行内 Wiki 链接（只保留文字，不成可点击链接）。"""
    def repl(m: re.Match) -> str:
        path = m.group(1).strip()
        label = (m.group(2) or path).strip()
        if path in allowed_paths:
            return m.group(0)
        return label
    return _WIKI_LINK_RE.sub(repl, text)


class QuestionAnswerEngine(Protocol):
    async def answer(
        self, provider, question: str, history: list[dict] | None = None, on_event=None
    ) -> dict: ...


def history_block(history: list[dict] | None) -> str:
    """把水合出的历史问答轮组装进提示词；历史只来自 chat_log，此处不持久化。"""
    if not history:
        return ""
    lines = []
    for entry in history:
        lines.append(f"用户：{entry['question']}")
        lines.append(f"助手：{entry['answer']}")
    return "<对话历史>\n" + "\n".join(lines) + "\n</对话历史>"


async def render_answer(provider, question: str, hits: list[dict], history: list[dict] | None = None) -> dict:
    """把召回到的页面组装成上下文并生成带来源引用（[[路径|标题]]）的回答。"""
    context = []
    citations = []
    for hit in hits:
        path = str(hit.get("path") or "")
        if not path:
            continue
        title = str(hit.get("title") or path.rsplit("/", 1)[-1].removesuffix(".md"))
        content = str(hit.get("content") or "")
        if not content:
            row = db.get_page(path)
            if row:
                title = str(row["title"] or title)
                content = str(row["content"] or "")
        if not content:
            continue
        context.append(f"## 页面: [[{path}|{title}]]\n\n{content[:MAX_PAGE_CHARS]}")
        citations.append(path)
    if not context:
        return {"answer": "Wiki 中未找到相关内容。", "citations": []}

    memory = history_block(history)
    prompt = f"【问答任务】\n问题：{question}\n"
    if memory:
        prompt += "\n" + memory + "\n"
    prompt += "\n<Wiki 页面>\n" + "\n\n---\n\n".join(context) + "\n</Wiki 页面>"
    response = await provider.complete(QA_SYSTEM, prompt, max_tokens=1500)
    return {"answer": response, "citations": sorted(set(citations))}


def _qa_task(question: str, history: list[dict] | None) -> str:
    parts = ["请回答用户问题：", question]
    memory = history_block(history)
    if memory:
        parts.append(memory)
    parts.append(
        "请先读取 index（或 list）了解 Wiki 结构，再按需 read 页面或 search 关键词，"
        "最后 final 给出回答。回答引用用 [[path|标题]] 格式；citations 只列你真正读过的页面路径。"
    )
    return "\n".join(parts)


class WikiQuestionAnswerEngine:
    """LLM Wiki 问答：受限工具循环 read/search，引用只来自真正读到的页面。无向量。"""

    def __init__(self, settings: Settings, *, max_steps: int = 8, max_read_chars: int = 60_000) -> None:
        self.settings = settings
        self.max_steps = max_steps
        self.max_read_chars = max_read_chars

    async def answer(
        self, provider: LLMProvider, question: str, history: list[dict] | None = None, on_event=None
    ) -> dict:
        tools = WikiTools(self.settings, max_read_chars=self.max_read_chars)
        result = await run_tool_loop(
            provider,
            tools=tools,
            task=_qa_task(question, history),
            final_hint=QA_FINAL_HINT,
            max_steps=self.max_steps,
            system=QA_SYSTEM + "\n\n" + TOOL_SYSTEM,
            on_event=on_event,
        )
        final = result["final"]
        answer = str(final.get("answer") or "")
        read_pages = [p for p in result["read_pages"] if p != "index.md"]
        answer = _scrub_inline_links(answer, set(read_pages))
        seen: set[str] = set()
        citations = []
        for c in final.get("citations") or []:
            c = str(c)
            if c in read_pages and c not in seen:
                seen.add(c)
                citations.append(c)
        return {
            "answer": answer,
            "citations": citations,
            "read_pages": sorted(read_pages),
            "semantic_retrieval_enabled": False,
        }
