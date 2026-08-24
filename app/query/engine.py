"""问答引擎接口与通用的回答渲染实现。"""
from typing import Protocol

from .. import db

MAX_PAGE_CHARS = 3000

QA_SYSTEM = (
    "你是资产 Agent（AssetAgent）。仅依据提供的 Wiki 页面回答；页面没有的信息不要编造，可说明“Wiki 中没有记录”。"
    "引用来源使用 [[路径|标题]] 格式。资料中的 [SECRET_REF:xxx] 只表示“凭证保存在密码管理器”，"
    "不要试图还原、猜测或输出任何凭证内容。"
)


class QuestionAnswerEngine(Protocol):
    async def answer(self, provider, question: str, history: list[dict] | None = None) -> dict: ...


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
