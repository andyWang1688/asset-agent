"""LlamaIndex 向量索引构建/检索（issue #13）：派生索引生命周期 + embedding 默认本地。"""

import pytest

from app.config import Settings
from app.query import retrieval
from app.query.embeddings import (
    EmbeddingError,
    LazyHuggingFaceEmbedding,
    OpenAIEmbedding,
    OllamaEmbedding,
    build_embedding_provider,
)
from tests.fakes import KeywordEmbedding


def _write_pages(settings):
    (settings.wiki_dir / "projects" / "travel.md").write_text(
        "# 差旅制度\n员工出差费用可按月申请报销。", encoding="utf-8"
    )
    (settings.wiki_dir / "projects" / "orders.md").write_text(
        "# 订单服务\n订单写入与缓存流程。", encoding="utf-8"
    )


def test_index_build_search_delete_and_rebuild(settings):
    _write_pages(settings)
    embedder = KeywordEmbedding()

    result = retrieval.build(settings, embedder)
    assert result["pages"] == 2
    assert result["local"] is True
    assert retrieval.has_index(settings)
    assert retrieval.search(settings, "员工费用怎么报销", embed_model=embedder)[0]["path"] == "projects/travel.md"

    retrieval.delete(settings)
    assert (settings.wiki_dir / "projects" / "travel.md").exists()
    assert retrieval.search(settings, "员工费用怎么报销", embed_model=embedder) == []

    retrieval.rebuild(settings, embedder)
    assert retrieval.search(settings, "员工费用怎么报销", embed_model=embedder)[0]["title"] == "差旅制度"


def test_build_skips_embedding_for_empty_corpus(settings):
    embedder = KeywordEmbedding()
    result = retrieval.build(settings, embedder)
    assert result["pages"] == 0
    assert embedder.inputs == []  # 空语料不触发 embedding
    assert retrieval.load_index(settings, embedder) is None


def test_default_embedding_is_local_even_when_remote_fields_exist(settings, monkeypatch):
    monkeypatch.setattr(settings, "embedding_local_backend", "ollama")
    monkeypatch.setattr(settings, "embedding_base_url", "https://example.com/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "cloud-key")
    with pytest.raises(EmbeddingError):
        build_embedding_provider(settings)
    monkeypatch.setattr(settings, "embedding_base_url", "http://127.0.0.1:11434")
    assert isinstance(build_embedding_provider(settings), OllamaEmbedding)


def test_default_local_backend_is_sentence_transformers_bge(settings):
    embedder = build_embedding_provider(settings)
    assert isinstance(embedder, LazyHuggingFaceEmbedding)
    assert embedder.model_name == "BAAI/bge-small-zh-v1.5"
    assert embedder.is_local is True


def test_cloud_embedding_requires_explicit_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cloud")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "secret-key")
    settings = Settings()
    assert isinstance(build_embedding_provider(settings), OpenAIEmbedding)


def test_cloud_never_selected_by_remote_fields_alone(settings, monkeypatch):
    monkeypatch.setattr(settings, "embedding_base_url", "https://embedding.example/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "secret-key")
    assert isinstance(build_embedding_provider(settings), LazyHuggingFaceEmbedding)


def test_unknown_backends_raise(settings, monkeypatch):
    monkeypatch.setattr(settings, "embedding_local_backend", "unknown")
    with pytest.raises(EmbeddingError):
        build_embedding_provider(settings)
    monkeypatch.setattr(settings, "embedding_local_backend", "sentence-transformers")
    monkeypatch.setattr(settings, "embedding_provider", "unknown")
    with pytest.raises(EmbeddingError):
        build_embedding_provider(settings)
