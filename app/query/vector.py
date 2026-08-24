"""File-backed local vector index for the Wiki.

Markdown remains the source of truth.  The JSON written here contains only
sanitized page metadata/content and derived vectors, so it can be deleted and
rebuilt at any time without touching the Wiki.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from pathlib import Path

from .. import db
from ..security import redactor
from . import index as file_index
from .embeddings import EmbeddingError, EmbeddingProvider, build_embedding_provider

VECTOR_INDEX_FILENAME = "wiki-vector-index.json"
VECTOR_INDEX_VERSION = 1


def vector_index_path(settings) -> Path:
    return settings.data_dir / VECTOR_INDEX_FILENAME


# Alternative public name for integrations that call the artifact an index.
index_path = vector_index_path


def _safe_page(path: str, title: str, content: str) -> dict:
    clean_content, _ = redactor.sanitize_llm_output(content or "")
    clean_title, _ = redactor.sanitize_llm_output(title or path.rsplit("/", 1)[-1].removesuffix(".md"))
    return {"path": str(path), "title": clean_title, "content": clean_content}


def _source_pages(settings) -> list[dict]:
    """Read and sanitize pages from Markdown, the sole knowledge source."""
    return [_safe_page(p["path"], p["title"], p["content"]) for p in file_index._pages(settings)]


def _provider_metadata(provider: EmbeddingProvider) -> dict:
    dimensions = getattr(provider, "dimensions", None)
    return {
        "name": str(getattr(provider, "name", provider.__class__.__name__)),
        "model": str(getattr(provider, "model", "") or ""),
        "dimensions": int(dimensions) if dimensions is not None else None,
        "local": bool(getattr(provider, "is_local", True)),
    }


def _as_vector(value: Sequence[float]) -> list[float]:
    vector = [float(item) for item in value]
    norm = math.sqrt(sum(item * item for item in vector))
    if not vector or not math.isfinite(norm) or norm == 0:
        raise EmbeddingError("embedding 返回空向量或零向量")
    return [item / norm for item in vector]


def build(settings, embedding_provider: EmbeddingProvider | None = None, provider=None) -> dict:
    """Build/replace the vector index from the current sanitized Wiki pages."""
    embedder = embedding_provider or provider or build_embedding_provider(settings)
    pages = _source_pages(settings)
    texts = [f"{page['title']}\n{page['content']}" for page in pages]
    vectors = embedder.embed_documents(texts) if texts else []
    if len(vectors) != len(pages):
        raise EmbeddingError("embedding 返回数量与页面数量不匹配")

    payload_pages = []
    dimensions = None
    for page, vector in zip(pages, vectors):
        normalized = _as_vector(vector)
        dimensions = dimensions or len(normalized)
        if len(normalized) != dimensions:
            raise EmbeddingError("embedding 向量维度不一致")
        payload_pages.append({**page, "vector": normalized})

    metadata = _provider_metadata(embedder)
    metadata["dimensions"] = dimensions or metadata.get("dimensions") or 0
    payload = {"version": VECTOR_INDEX_VERSION, "embedding": metadata, "pages": payload_pages}
    target = vector_index_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
    return {
        "path": str(target),
        "pages": len(payload_pages),
        "dimensions": metadata["dimensions"],
        "embedding": metadata["name"],
        "local": metadata["local"],
    }


def rebuild(settings, embedding_provider: EmbeddingProvider | None = None, provider=None) -> dict:
    return build(settings, embedding_provider=embedding_provider, provider=provider)


def delete(settings) -> None:
    vector_index_path(settings).unlink(missing_ok=True)


def load(settings) -> dict:
    try:
        value = json.loads(vector_index_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": VECTOR_INDEX_VERSION, "embedding": {}, "pages": []}
    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        return {"version": VECTOR_INDEX_VERSION, "embedding": {}, "pages": []}
    return value


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right))


def search(
    settings,
    query: str,
    limit: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
    provider=None,
    min_score: float = 0.05,
) -> list[dict]:
    """Return the highest cosine-similarity pages with page-level metadata."""
    query = " ".join(str(query or "").split())
    if not query or limit <= 0:
        return []
    loaded = load(settings)
    pages = loaded.get("pages") or []
    if not pages:
        return []
    embedder = embedding_provider or provider or build_embedding_provider(settings)
    query_vector = _as_vector(embedder.embed_query(query))
    scored: list[tuple[float, str, dict]] = []
    for page in pages:
        try:
            score = _dot(query_vector, page.get("vector") or [])
        except (TypeError, ValueError):
            continue
        if score > min_score:
            scored.append((score, str(page.get("path", "")), page))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{**page, "score": score} for score, _, page in scored[:limit]]


def has_index(settings) -> bool:
    return vector_index_path(settings).is_file()


# Naming aliases make the module usable as a drop-in derived-index builder.
build_index = build
rebuild_index = rebuild
delete_index = delete
load_index = load
search_index = search
build_vector_index = build
rebuild_vector_index = rebuild
delete_vector_index = delete
search_vector = search
