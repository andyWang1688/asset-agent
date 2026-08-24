"""问答引擎接口、FTS5 实现和可选的本地向量/混合检索实现。"""
import asyncio
from typing import Protocol

from .. import db
from . import vector
from .embeddings import EmbeddingProvider

MAX_PAGE_CHARS = 3000

QA_SYSTEM = (
    "你是资产 Agent（AssetAgent）。仅依据提供的 Wiki 页面回答；页面没有的信息不要编造，可说明“Wiki 中没有记录”。"
    "引用来源使用 [[路径|标题]] 格式。资料中的 [SECRET_REF:xxx] 只表示“凭证保存在密码管理器”，"
    "不要试图还原、猜测或输出任何凭证内容。"
)


class QuestionAnswerEngine(Protocol):
    async def answer(self, provider, question: str) -> dict: ...


async def render_answer(provider, question: str, hits: list[dict]) -> dict:
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

    prompt = (
        f"【问答任务】\n问题：{question}\n\n<Wiki 页面>\n"
        + "\n\n---\n\n".join(context)
        + "\n</Wiki 页面>"
    )
    response = await provider.complete(QA_SYSTEM, prompt, max_tokens=1500)
    return {"answer": response, "citations": sorted(set(citations))}


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


class VectorQuestionAnswerEngine:
    """Page-level vector retrieval backed by the rebuildable Wiki index.

    The engine has the same ``answer(provider, question)`` seam and response
    shape as :class:`FTS5QuestionAnswerEngine`.  Embeddings are created from
    sanitized Markdown only; the question has already passed the service
    security gate before this method is called.
    """

    def __init__(
        self,
        settings,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        embedding: EmbeddingProvider | None = None,
        embedder: EmbeddingProvider | None = None,
        limit: int = 5,
        min_score: float = 0.05,
        auto_build: bool = True,
    ) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider or embedding or embedder
        self.limit = limit
        self.min_score = min_score
        self.auto_build = auto_build

    async def _ensure_index(self) -> None:
        if self.auto_build and not vector.has_index(self.settings):
            await asyncio.to_thread(
                vector.rebuild,
                self.settings,
                self.embedding_provider,
            )

    async def answer(self, provider, question: str) -> dict:
        await self._ensure_index()
        hits = await asyncio.to_thread(
            vector.search,
            self.settings,
            question,
            limit=self.limit,
            embedding_provider=self.embedding_provider,
            min_score=self.min_score,
        )
        return await render_answer(provider, question, hits)


# Short aliases used by integrations that call the retrieval mode "vector".
VectorEngine = VectorQuestionAnswerEngine
LocalVectorQuestionAnswerEngine = VectorQuestionAnswerEngine
