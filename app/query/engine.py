"""问答引擎接口及当前的 FTS5 实现。"""
from typing import Protocol

from .. import db

MAX_PAGE_CHARS = 3000

QA_SYSTEM = (
    "你是资产 Agent（AssetAgent）。仅依据提供的 Wiki 页面回答；页面没有的信息不要编造，可说明“Wiki 中没有记录”。"
    "引用来源使用 [[路径|标题]] 格式。资料中的 [SECRET_REF:xxx] 只表示“凭证保存在密码管理器”，"
    "不要试图还原、猜测或输出任何凭证内容。"
)


class QuestionAnswerEngine(Protocol):
    async def answer(self, provider, question: str) -> dict: ...


class FTS5QuestionAnswerEngine:
    """现有 FTS5 检索与回答生成实现。"""

    async def answer(self, provider, question: str) -> dict:
        hits = db.search_pages(question, limit=5)
        if not hits:
            return {"answer": "Wiki 中未找到相关内容。", "citations": []}

        context = []
        for hit in hits:
            row = db.get_page(hit["path"])
            if row:
                context.append(
                    f"## 页面: [[{hit['path']}|{hit['title']}]]\n\n"
                    f"{row['content'][:MAX_PAGE_CHARS]}"
                )
        prompt = (
            f"【问答任务】\n问题：{question}\n\n<Wiki 页面>\n"
            + "\n\n---\n\n".join(context)
            + "\n</Wiki 页面>"
        )
        response = await provider.complete(QA_SYSTEM, prompt, max_tokens=1500)
        return {"answer": response, "citations": sorted({hit["path"] for hit in hits})}
