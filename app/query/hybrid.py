"""BM25 + 向量混合召回与重排，提供第三个可整体替换的问答引擎实现。

关键词支路走 BM25，语义支路走向量，两条支路 RRF 融合为纯召回顺序；
重排器可配置、可停用（``RERANKER=off`` 退回纯召回）。索引仍是可删除重建的派生文件。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from . import bm25, vector
from .embeddings import EmbeddingError, EmbeddingProvider
from .engine import render_answer

RRF_K = 60


def fuse(bm25_hits: list[dict], vector_hits: list[dict], k: int = RRF_K) -> list[dict]:
    """Reciprocal rank fusion：两支路的位次越靠前，融合分越高。"""
    merged: dict[str, dict] = {}
    for rank, hit in enumerate(bm25_hits):
        path = str(hit.get("path") or "")
        if not path:
            continue
        entry = merged.setdefault(path, dict(hit))
        entry["rrf"] = entry.get("rrf", 0.0) + 1.0 / (k + rank + 1)
    for rank, hit in enumerate(vector_hits):
        path = str(hit.get("path") or "")
        if not path:
            continue
        entry = merged.setdefault(path, dict(hit))
        entry["rrf"] = entry.get("rrf", 0.0) + 1.0 / (k + rank + 1)
    return sorted(merged.values(), key=lambda item: (-item["rrf"], item["path"]))


def recall(
    settings,
    question: str,
    *,
    limit: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
    min_score: float = 0.05,
) -> list[dict]:
    """混合召回：BM25 与向量两支路 RRF 融合，返回按融合分排序的候选页。"""
    pages = vector.load(settings).get("pages") or []
    if not pages:
        return []
    bm25_hits = bm25.search(pages, question, limit=limit)
    vector_hits = vector.search(
        settings,
        question,
        limit=limit,
        embedding_provider=embedding_provider,
        min_score=min_score,
    )
    return fuse(bm25_hits, vector_hits)[:limit]


class LocalReranker:
    """本地精排器：候选页上按「融合分 × 权重 + 向量相似度 × (1-权重)」重排序。"""

    def __init__(self, embedding_provider: EmbeddingProvider, *, weight: float = 0.5) -> None:
        self.embedding_provider = embedding_provider
        self.weight = float(weight)

    def __call__(self, question: str, candidates: list[dict]) -> list[dict]:
        query_vector = vector._as_vector(self.embedding_provider.embed_query(question))
        reranked = [
            (
                self.weight * float(candidate.get("rrf") or 0.0)
                + (1.0 - self.weight) * vector._dot(query_vector, candidate.get("vector") or []),
                candidate,
            )
            for candidate in candidates
        ]
        reranked.sort(key=lambda item: (-item[0], item[1].get("path", "")))
        return [candidate for _, candidate in reranked]


def build_reranker(settings, embedding_provider: EmbeddingProvider, mode: str | None = None) -> Callable | None:
    """按配置装配重排器；``off`` 停用（退回纯召回），``local`` 使用本地精排。"""
    selected = str(mode if mode is not None else getattr(settings, "reranker", "off")).strip().lower()
    if selected in {"off", "none", "false", ""}:
        return None
    if selected == "local":
        return LocalReranker(embedding_provider)
    raise EmbeddingError(f"未知 reranker: {selected}")


class HybridQuestionAnswerEngine:
    """BM25 + 向量混合召回 + 可选重排的问答引擎。

    与 FTS5/向量引擎同缝同响应结构；``reranker`` 为 None 表示停用（纯召回顺序）。
    问题已通过 service 安全闸门后才调用本方法。
    """

    def __init__(
        self,
        settings,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        reranker: Callable | None = None,
        limit: int = 5,
        min_score: float = 0.05,
        auto_build: bool = True,
    ) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.limit = limit
        self.min_score = min_score
        self.auto_build = auto_build

    async def _ensure_index(self) -> None:
        if self.auto_build and not vector.has_index(self.settings):
            await asyncio.to_thread(vector.rebuild, self.settings, self.embedding_provider)

    async def answer(self, provider, question: str) -> dict:
        await self._ensure_index()
        hits = await asyncio.to_thread(
            recall,
            self.settings,
            question,
            limit=self.limit,
            embedding_provider=self.embedding_provider,
            min_score=self.min_score,
        )
        if hits and self.reranker is not None:
            hits = await asyncio.to_thread(self.reranker, question, hits)
        return await render_answer(provider, question, hits)


# Short aliases used by integrations that call the retrieval mode "hybrid".
HybridEngine = HybridQuestionAnswerEngine
