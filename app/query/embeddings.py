"""Embedding seam for index building and querying, built on LlamaIndex components.

The default provider is local-only (BGE via sentence-transformers); Ollama is an
alternative local backend.  A cloud OpenAI-compatible provider is only selected
when explicitly configured — merely filling a URL or key never changes the
default, so Wiki text stays on the machine during index building.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import ClassVar
from urllib.parse import urlsplit

from huggingface_hub.constants import HF_HUB_CACHE
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"


def _hf_cache_dir() -> str:
    """HF 模型缓存目录：复用 huggingface_hub 标准缓存（与手动预下载同目录）。"""
    return os.environ.get("HF_HOME") or str(HF_HUB_CACHE)


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend cannot produce valid vectors."""


class LazyHuggingFaceEmbedding(HuggingFaceEmbedding):
    """Local BGE embedding (sentence-transformers) that loads lazily.

    Construction is cheap: the SentenceTransformer model is only loaded on the
    first embed call, keeping app startup and model-free code paths fast.
    ``local_files_only`` is enforced by default so index building can never
    trigger network access.
    """

    is_local: ClassVar[bool] = True

    def __init__(self, **kwargs):
        # 只初始化 pydantic 字段（不加载模型），保证 resolve_embed_model 等
        # 框架路径在模型装载前也能正常读写 callback_manager 等字段。
        BaseEmbedding.__init__(
            self,
            model_name=str(kwargs.get("model_name") or DEFAULT_LOCAL_MODEL),
            embed_batch_size=kwargs.get("embed_batch_size", 10),
            callback_manager=kwargs.get("callback_manager"),
            num_workers=kwargs.get("num_workers"),
            embeddings_cache=kwargs.get("embeddings_cache"),
            rate_limiter=kwargs.get("rate_limiter"),
        )
        object.__setattr__(self, "_lazy_init_kwargs", dict(kwargs))
        object.__setattr__(self, "_lazy_loaded", False)

    def _ensure_loaded(self) -> None:
        if self._lazy_loaded:
            return
        HuggingFaceEmbedding.__init__(self, **self._lazy_init_kwargs)
        object.__setattr__(self, "_lazy_loaded", True)

    def get_text_embedding(self, text: str) -> list[float]:
        self._ensure_loaded()
        return super().get_text_embedding(text)

    def get_query_embedding(self, query: str) -> list[float]:
        self._ensure_loaded()
        return super().get_query_embedding(query)

    async def aget_text_embedding(self, text: str) -> list[float]:
        self._ensure_loaded()
        return await super().aget_text_embedding(text)

    async def aget_query_embedding(self, query: str) -> list[float]:
        self._ensure_loaded()
        return await super().aget_query_embedding(query)

    def get_text_embedding_batch(self, texts: list[str], show_progress: bool = False, **kwargs) -> list[list[float]]:
        self._ensure_loaded()
        return super().get_text_embedding_batch(texts, show_progress=show_progress, **kwargs)

    async def aget_text_embedding_batch(self, texts: list[str], show_progress: bool = False, **kwargs) -> list[list[float]]:
        self._ensure_loaded()
        return await super().aget_text_embedding_batch(texts, show_progress=show_progress, **kwargs)


def _local_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return bool(address.is_loopback or address.is_private or address.is_link_local or address.is_reserved)
    except ValueError:
        pass
    try:
        addresses = {item[4][0].split("%")[0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not (parsed.is_loopback or parsed.is_private or parsed.is_link_local or parsed.is_reserved):
            return False
    return True


def validate_local_endpoint(base_url: str) -> str | None:
    host = urlsplit((base_url or "").strip()).hostname
    if not host:
        return "本地 embedding 必须填写有效的 API 地址"
    if not _local_host(host):
        return "本地 embedding 仅允许 localhost/内网端点"
    return None


def _setting(settings, *names: str, default=None):
    for name in names:
        value = getattr(settings, name, None)
        if value is not None and value != "":
            return value
    return default


def build_embedding_provider(settings, provider: str | None = None):
    """Build a LlamaIndex embedding model from settings.

    ``local`` is the fail-safe default.  A cloud provider is selected only by
    an explicit provider value; supplying a remote URL/key alone does nothing.
    页面保存的检索配置优先于环境变量（未页面配置时行为与旧版完全一致）。
    """
    if provider is None:
        from . import retrieval_config

        page = retrieval_config.page_config()
        if page is not None:
            return retrieval_config.build_page_embedder(settings, page)
    selected = str(
        provider
        or _setting(settings, "embedding_provider", "embedding_backend", default="local")
    ).strip().lower()
    model = str(_setting(settings, "embedding_model", default=DEFAULT_LOCAL_MODEL))

    if selected in {"cloud", "openai"}:
        base_url = str(_setting(settings, "embedding_base_url", default=""))
        if not base_url:
            raise EmbeddingError("云端 embedding 必须填写 API 地址")
        # model_name 直通（OpenAI 兼容端点可用任意模型名，不走 OpenAI 内置枚举）。
        return OpenAIEmbedding(
            model_name=model,
            api_base=base_url,
            api_key=str(_setting(settings, "embedding_api_key", default="") or ""),
            embed_batch_size=32,
        )
    if selected != "local":
        raise EmbeddingError(f"未知 embedding provider: {selected}")

    backend = str(_setting(settings, "embedding_local_backend", default="sentence-transformers")).strip().lower()
    if backend in {"sentence-transformers", "sentence_transformers", "st"}:
        local_only = bool(_setting(settings, "embedding_local_only", default=True))
        return LazyHuggingFaceEmbedding(
            model_name=model,
            cache_folder=_hf_cache_dir(),
            model_kwargs={"local_files_only": local_only},
        )
    if backend == "ollama":
        base_url = str(_setting(settings, "embedding_base_url", default="") or "http://127.0.0.1:11434")
        error = validate_local_endpoint(base_url)
        if error:
            raise EmbeddingError(error)
        return OllamaEmbedding(model_name=model, base_url=base_url)
    raise EmbeddingError(f"未知本地 embedding backend: {backend}")
