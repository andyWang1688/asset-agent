"""LlamaIndex 文件级派生索引：Markdown 是唯一事实源。

索引目录（``<DATA_DIR>/llamaindex``）由 VectorStoreIndex + SimpleVectorStore 持久化，
可整目录删除、可从 Markdown 全量重建。页面文本在进入 embedding 前先过脱敏边界
防护（与文件级索引同一清洗点），秘密原文不进入模型与索引文件。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage

from . import index as file_index
from .embeddings import build_embedding_provider

INDEX_DIR_NAME = "llamaindex"
# BM25 关键词支路的分词口径：ASCII 词元 + 中文字符（与切换前 bigram 初筛同源词元）。
BM25_TOKEN_PATTERN = r"(?u)[a-zA-Z0-9_]+|[\u4e00-\u9fff]"


def index_dir(settings) -> Path:
    return settings.data_dir / INDEX_DIR_NAME


def has_index(settings) -> bool:
    return (index_dir(settings) / "index_store.json").is_file()


def _pages(settings) -> list[dict]:
    """sanitized 页面列表：Markdown 事实源 + 脱敏边界防护（秘密原文不进入派生索引）。"""
    return [
        {"path": p["path"], "title": p["title"], "content": p["content"]}
        for p in file_index._pages(settings)
    ]


def _documents(settings) -> list[Document]:
    docs = []
    for page in _pages(settings):
        docs.append(
            Document(
                text=f"{page['title']}\n{page['content']}",
                metadata={"path": page["path"], "title": page["title"]},
            )
        )
    return docs


def build(settings, embed_model=None, provider=None, staging: Path | None = None) -> dict:
    """从 Markdown 全量重建 LlamaIndex 向量索引并持久化到本地目录。

    ``staging`` 给定临时目录时索引先建到该目录（由调用方完成后原子换名），
    正式目录在整个重建期间保持旧索引可读（重建期间旧索引继续服务）。
    """
    embedder = embed_model or provider or build_embedding_provider(settings)
    docs = _documents(settings)
    target = staging or index_dir(settings)
    shutil.rmtree(target, ignore_errors=True)
    if not docs:
        # 空语料：目录即空索引，不触发 embedding。
        target.mkdir(parents=True, exist_ok=True)
        return {"path": str(target), "pages": 0, "embedding": _embedding_name(embedder), "local": True}
    storage = StorageContext.from_defaults()
    index = VectorStoreIndex.from_documents(
        docs, embed_model=embedder, storage_context=storage, show_progress=False
    )
    storage.persist(persist_dir=target)
    return {
        "path": str(target),
        "pages": len(docs),
        "embedding": _embedding_name(embedder),
        "local": bool(getattr(embedder, "is_local", True)),
    }


def rebuild(settings, embed_model=None, provider=None) -> dict:
    return build(settings, embed_model=embed_model, provider=provider)


def delete(settings) -> None:
    """删除派生索引目录，不触碰 Markdown 事实源。"""
    shutil.rmtree(index_dir(settings), ignore_errors=True)


def _embedding_name(embedder) -> str:
    name = getattr(embedder, "model_name", None) or type(embedder).__name__
    return str(name)


def load_index(settings, embed_model=None, provider=None):
    """加载持久化的向量索引；缺失或损坏视为空索引（调用方可重建）。"""
    path = index_dir(settings)
    if not has_index(settings):
        return None
    embedder = embed_model or provider or build_embedding_provider(settings)
    try:
        storage = StorageContext.from_defaults(persist_dir=path)
        return load_index_from_storage(storage, embed_model=embedder)
    except (OSError, ValueError, KeyError, AttributeError, json.JSONDecodeError):
        return None


def search(
    settings,
    query: str,
    limit: int = 5,
    embed_model=None,
    provider=None,
) -> list[dict]:
    """向量支路检索：返回按相似度排序的页面（path/title/content/score）。"""
    from .hybrid import nodes_to_hits

    index = load_index(settings, embed_model=embed_model, provider=provider)
    if index is None or not index.docstore.docs:
        return []
    retriever = index.as_retriever(similarity_top_k=limit)
    return nodes_to_hits(retriever.retrieve(query))[:limit]


# 命名别名：保持“索引构建器”语义，供外部按语义引用。
build_index = build
rebuild_index = rebuild
delete_index = delete
search_index = search
search_vector = search
