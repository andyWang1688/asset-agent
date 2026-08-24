"""LlamaIndex 混合问答引擎：BM25+向量 RRF 融合召回 + 可选重排。

关键词支路走 llama-index-retrievers-bm25（BM25Retriever），语义支路走向量索引
（VectorStoreIndex），两条支路由 QueryFusionRetriever 以 RRF 融合；重排器为
SentenceTransformerRerank（本地 cross-encoder，可配置、可停用 ``RERANKER=off``）。
索引仍是可删除重建的派生目录。API 契约、多轮记忆水合、安全闸门在 service 层，不在此处。
"""

from __future__ import annotations

import asyncio

from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from llama_index.retrievers.bm25 import BM25Retriever

from . import retrieval
from .embeddings import EmbeddingError, build_embedding_provider
from .engine import render_answer

DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"


class NonZeroBM25Retriever(BM25Retriever):
    """BM25Retriever 扩展：丢弃零分页。

    bm25s 返回的零分页会把无匹配页塞进 RRF 融合（拿到位次分），
    与切换前“关键词支路只返回命中页”的基线行为不符；这里恢复该行为。
    """

    def _retrieve(self, query_bundle):
        return [node for node in super()._retrieve(query_bundle) if (node.score or 0.0) > 0]


def nodes_to_hits(nodes: list[NodeWithScore]) -> list[dict]:
    """把 LlamaIndex 召回节点转成引擎契约结构（path/title/content/score）。"""
    hits = []
    for node in nodes:
        meta = node.node.metadata or {}
        path = str(meta.get("path") or "")
        if not path:
            continue
        title = str(meta.get("title") or path.rsplit("/", 1)[-1].removesuffix(".md"))
        hits.append(
            {
                "path": path,
                "title": title,
                "content": str(node.node.get_content()),
                "score": float(node.score or 0.0),
            }
        )
    return hits


def recall(
    settings,
    question: str,
    *,
    limit: int = 5,
    embed_model=None,
    min_score: float = 0.0,
) -> list[dict]:
    """混合召回：BM25 与向量两支路 RRF 融合，返回按融合分排序的候选页。"""
    return HybridQuestionAnswerEngine(
        settings, embed_model=embed_model, limit=limit, min_score=min_score
    ).retrieve(question)


def build_reranker(settings, mode: str | None = None, *, top_n: int = 5):
    """按配置装配 LlamaIndex 重排器；``off`` 停用（退回纯召回），``local`` 用本地 cross-encoder。"""
    page_model = None
    if mode is None:
        from . import retrieval_config

        page = retrieval_config.page_config()
        if page is not None:
            # 页面配置优先：reranker_enabled=false 即 off；否则用页面重排模型。
            mode = "local" if page["reranker_enabled"] else "off"
            page_model = page["reranker_model"] or None
    selected = str(mode if mode is not None else getattr(settings, "reranker", "off")).strip().lower()
    if selected in {"off", "none", "false", ""}:
        return None
    if selected == "local":
        model = str(page_model or getattr(settings, "reranker_model", None) or DEFAULT_RERANK_MODEL)
        local_only = bool(getattr(settings, "embedding_local_only", True))
        return SentenceTransformerRerank(
            model=model,
            top_n=int(top_n),
            cross_encoder_kwargs={"local_files_only": local_only},
        )
    raise EmbeddingError(f"未知 reranker: {selected}")


class HybridQuestionAnswerEngine:
    """BM25+向量混合召回 + 可选重排的问答引擎（LlamaIndex 组件装配）。

    与其它引擎实现同缝同响应结构；``reranker`` 未显式传入时按 settings 装配，
    ``off`` 表示停用（纯召回顺序）。embedding 与重排模型都在首次使用才加载，
    启动零开销；问题已通过 service 安全闸门后才调用本方法。
    """

    def __init__(
        self,
        settings,
        embed_model=None,
        reranker=None,
        *,
        limit: int = 5,
        min_score: float = 0.0,
        auto_build: bool = True,
        reranker_from_settings: bool = False,
    ) -> None:
        self.settings = settings
        self._embed_model = embed_model
        self._reranker = reranker
        # 显式构造（含测试）不重排；仅 app 装配的引擎按 settings 惰性装配重排器。
        self._use_settings_reranker = reranker_from_settings and reranker is None
        self.limit = limit
        self.min_score = min_score
        self.auto_build = auto_build

    def _embedding(self):
        if self._embed_model is None:
            # 页面检索配置可运行时变更：未显式注入时每次按当前配置装配
            # （构造廉价，权重惰性加载），不缓存旧配置。
            return build_embedding_provider(self.settings)
        return self._embed_model

    def _resolve_reranker(self):
        if self._use_settings_reranker:
            # 同上：按当前配置实时装配，不用启动时快照。
            return build_reranker(self.settings, top_n=self.limit)
        return self._reranker

    async def _ensure_index(self) -> None:
        if self.auto_build and not retrieval.has_index(self.settings):
            await asyncio.to_thread(retrieval.build, self.settings, self._embedding())

    def retrieve(self, question: str) -> list[dict]:
        index = retrieval.load_index(self.settings, self._embedding())
        if index is None or not index.docstore.docs:
            return []
        vector_retriever = index.as_retriever(similarity_top_k=self.limit)
        bm25_retriever = NonZeroBM25Retriever.from_defaults(
            docstore=index.docstore,
            similarity_top_k=self.limit,
            token_pattern=retrieval.BM25_TOKEN_PATTERN,
        )
        fusion = QueryFusionRetriever(
            [vector_retriever, bm25_retriever],
            llm=MockLLM(),
            similarity_top_k=self.limit,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            num_queries=1,
            use_async=False,
        )
        nodes = fusion.retrieve(QueryBundle(question))
        reranker = self._resolve_reranker() if nodes else None
        if nodes and reranker is not None:
            nodes = reranker.postprocess_nodes(nodes, QueryBundle(question))
        return [hit for hit in nodes_to_hits(nodes) if hit["score"] >= self.min_score]

    async def answer(self, provider, question: str, history: list[dict] | None = None) -> dict:
        await self._ensure_index()
        hits = await asyncio.to_thread(self.retrieve, question)
        return await render_answer(provider, question, hits, history=history)


# Short aliases used by integrations that call the retrieval mode "hybrid".
HybridEngine = HybridQuestionAnswerEngine
