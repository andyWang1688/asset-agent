"""检索配置：页面持久化配置（``retrieval_config`` 单行表），页面写入优先于环境变量。

与知识库/安全模型的 ``model_configs`` 表不同：检索配置是单实例单配置，不存在“角色/激活”，
只回答“后端路线 + 模型 + 重排器 + 云端端点”四个问题。API Key 走既有 AES-GCM 加密存储
（``crypto.seal``），任何读接口只返回 ``cloud_api_key_set`` 布尔值，不回显密文或明文。
"""

from __future__ import annotations

from .. import crypto, db
from ..config import Settings
from .embeddings import EmbeddingError, _hf_cache_dir
from .embeddings import LazyHuggingFaceEmbedding, OpenAIEmbedding, OllamaEmbedding, validate_local_endpoint

PROVIDER_ST = "sentence-transformers"
PROVIDER_OLLAMA = "ollama"
PROVIDER_CLOUD = "cloud"
PROVIDERS = (PROVIDER_ST, PROVIDER_OLLAMA, PROVIDER_CLOUD)

# 中文场景推荐（BGE 系入门款在前）；云端为 OpenAI 兼容端点的常见 embedding 模型名。
RECOMMENDED_EMBEDDINGS: dict[str, list[str]] = {
    PROVIDER_ST: ["BAAI/bge-small-zh-v1.5", "BAAI/bge-base-zh-v1.5", "BAAI/bge-large-zh-v1.5"],
    PROVIDER_OLLAMA: ["bge-m3", "quentinz/bge-large-zh-v1.5"],
    PROVIDER_CLOUD: ["text-embedding-3-small", "text-embedding-3-large"],
}
RECOMMENDED_RERANKERS = ["BAAI/bge-reranker-base", "BAAI/bge-reranker-v2-m3"]

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def page_config() -> dict | None:
    """页面已保存的配置；未保存返回 None（行为完全由环境变量决定）。"""
    try:
        row = db.get_retrieval_config()
    except RuntimeError:
        # db 未初始化（如无 workspace 的轻量测试）：视为未配置
        return None
    if row is None:
        return None
    return {
        "provider": row["provider"],
        "model": row["model"],
        "reranker_enabled": bool(row["reranker_enabled"]),
        "reranker_model": row["reranker_model"],
        "cloud_base_url": row["cloud_base_url"],
        "cloud_api_key_enc": row["cloud_api_key_enc"],
    }


def _local_backend(settings: Settings) -> str:
    return str(getattr(settings, "embedding_local_backend", "") or "sentence-transformers").strip().lower()


def _embedding_provider(settings: Settings) -> str:
    return str(getattr(settings, "embedding_provider", "local") or "local").strip().lower()


def env_signature(settings: Settings) -> dict:
    """环境变量推导出的有效检索配置（与 embeddings.build_embedding_provider 的环境分支同语义）。"""
    selected = _embedding_provider(settings)
    model = str(getattr(settings, "embedding_model", "") or "BAAI/bge-small-zh-v1.5")
    if selected in {"cloud", "openai"}:
        return {
            "provider": PROVIDER_CLOUD,
            "model": model,
            "cloud_base_url": str(getattr(settings, "embedding_base_url", "") or ""),
            "api_key": str(getattr(settings, "embedding_api_key", "") or ""),
        }
    backend = _local_backend(settings)
    if backend in {"ollama"}:
        return {
            "provider": PROVIDER_OLLAMA,
            "model": model,
            "base_url": str(getattr(settings, "embedding_base_url", "") or "") or DEFAULT_OLLAMA_BASE_URL,
        }
    return {"provider": PROVIDER_ST, "model": model}


def page_signature(page: dict, api_key: str = "") -> dict:
    """页面配置的嵌入签名（api_key 仅用于云端的运行时构建）。"""
    if page["provider"] == PROVIDER_CLOUD:
        return {"provider": PROVIDER_CLOUD, "model": page["model"],
                "cloud_base_url": page["cloud_base_url"], "api_key": api_key}
    if page["provider"] == PROVIDER_OLLAMA:
        return {"provider": PROVIDER_OLLAMA, "model": page["model"]}
    return {"provider": PROVIDER_ST, "model": page["model"]}


def embedding_signature(settings: Settings) -> dict:
    """当前生效的嵌入签名：页面优先，否则环境变量。用于判断保存是否导致向量不兼容。"""
    page = page_config()
    if page is not None:
        key = ""
        if page["cloud_api_key_enc"]:
            try:
                key = crypto.open_sealed(settings.local_key(), page["cloud_api_key_enc"]).decode("utf-8")
            except Exception:
                key = ""
        return page_signature(page, api_key=key)
    return env_signature(settings)


def build_page_embedder(settings: Settings, page: dict | None):
    """按页面配置构建 embedding 模型；page 为 None 时等价于环境变量路径。"""
    if page is None:
        from .embeddings import build_embedding_provider

        return build_embedding_provider(settings)
    if page["provider"] == PROVIDER_CLOUD:
        base_url = str(page["cloud_base_url"] or "").strip()
        if not base_url:
            raise EmbeddingError("云端 embedding 必须填写 API 地址")
        api_key = ""
        if page["cloud_api_key_enc"]:
            api_key = crypto.open_sealed(settings.local_key(), page["cloud_api_key_enc"]).decode("utf-8")
        return OpenAIEmbedding(model_name=page["model"], api_base=base_url, api_key=api_key, embed_batch_size=32)
    if page["provider"] == PROVIDER_OLLAMA:
        base_url = str(getattr(settings, "embedding_base_url", "") or "") or DEFAULT_OLLAMA_BASE_URL
        error = validate_local_endpoint(base_url)
        if error:
            raise EmbeddingError(error)
        return OllamaEmbedding(model_name=page["model"], base_url=base_url)
    # sentence-transformers：本地权重，沿用 EMBEDDING_LOCAL_ONLY 的离线/在线语义
    local_only = bool(getattr(settings, "embedding_local_only", True))
    return LazyHuggingFaceEmbedding(
        model_name=page["model"],
        cache_folder=_hf_cache_dir(),
        model_kwargs={"local_files_only": local_only},
    )


def build_test_embedder(settings: Settings, *, provider: str, model: str, base_url: str = "", api_key: str = ""):
    """测试端点用 embedder：与运行时同装配路径，但 sentence-transformers 允许联网下载缺失权重。"""
    if provider == PROVIDER_CLOUD:
        if not str(base_url or "").strip():
            raise EmbeddingError("云端 embedding 必须填写 API 地址")
        return OpenAIEmbedding(model_name=model, api_base=str(base_url).strip(), api_key=api_key, embed_batch_size=1)
    if provider == PROVIDER_OLLAMA:
        url = str(getattr(settings, "embedding_base_url", "") or "") or DEFAULT_OLLAMA_BASE_URL
        error = validate_local_endpoint(url)
        if error:
            raise EmbeddingError(error)
        return OllamaEmbedding(model_name=model, base_url=url)
    # 测试允许首次下载：缺权重时联网拉到 HF 缓存（持久卷），下载失败回友好错误。
    return LazyHuggingFaceEmbedding(
        model_name=model,
        cache_folder=_hf_cache_dir(),
        model_kwargs={"local_files_only": False},
    )


def friendly_error(provider: str, exc: Exception) -> str:
    """把底层异常映射为面向页面的友好文案；网络失败时给出 Ollama 替代路线指引。"""
    if isinstance(exc, EmbeddingError):
        return str(exc)
    name = type(exc).__name__
    if provider == PROVIDER_OLLAMA:
        return (
            f"Ollama 不可用（{name}）：请确认 Ollama 服务已启动且已拉取该模型，"
            "或改用本地 sentence-transformers 路线。"
        )
    if provider == PROVIDER_CLOUD:
        return f"云端端点不可用（{name}）：请检查 API 地址、Key 与网络连通性。"
    detail = str(exc).strip().replace("\n", " ")[:200] or name
    if "network" in detail.lower() or "connection" in detail.lower() or "timeout" in detail.lower():
        return f"模型下载失败（网络不可达）：请检查网络后重试，或改用本地 Ollama 路线（Ollama 需先拉取模型）。"
    return f"本地模型不可用（{name}）：请确认模型 ID 正确、权重已缓存，或改用本地 Ollama 路线。{detail}"
