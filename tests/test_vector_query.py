import json

import httpx

from app import db
from app.config import Settings
from app.query import vector
from app.query.embeddings import (
    CloudEmbeddingProvider,
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OllamaEmbeddingProvider,
    build_embedding_provider,
)
from app.query.engine import VectorQuestionAnswerEngine
from app.query import service
from tests.fakes import FakeProvider


class KeywordEmbedding(EmbeddingProvider):
    name = "test-local"
    model = "fixture"
    is_local = True

    def __init__(self):
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        result = []
        for text in texts:
            value = str(text)
            result.append([
                1.0 if "报销" in value or "差旅" in value else 0.0,
                1.0 if "订单" in value else 0.0,
                0.1,
            ])
        return result


def _write_pages(settings):
    (settings.wiki_dir / "projects" / "travel.md").write_text(
        "# 差旅制度\n员工出差费用可按月申请报销。", encoding="utf-8"
    )
    (settings.wiki_dir / "projects" / "orders.md").write_text(
        "# 订单服务\n订单写入与缓存流程。", encoding="utf-8"
    )


def test_vector_index_build_search_delete_and_rebuild(settings):
    _write_pages(settings)
    embedder = KeywordEmbedding()

    result = vector.build(settings, embedder)
    assert result["pages"] == 2
    assert result["local"] is True
    assert vector.search(settings, "员工费用怎么报销", embedding_provider=embedder)[0]["path"] == "projects/travel.md"

    vector.delete(settings)
    assert (settings.wiki_dir / "projects" / "travel.md").exists()
    assert vector.search(settings, "员工费用怎么报销", embedding_provider=embedder) == []

    vector.rebuild(settings, embedder)
    assert vector.search(settings, "员工费用怎么报销", embedding_provider=embedder)[0]["title"] == "差旅制度"


def test_default_embedding_is_local_even_when_remote_fields_exist(settings, monkeypatch):
    monkeypatch.setattr(settings, "embedding_local_backend", "ollama")
    monkeypatch.setattr(settings, "embedding_base_url", "https://example.com/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "cloud-key")
    try:
        build_embedding_provider(settings)
    except Exception as exc:
        assert "本地 embedding" in str(exc)
    monkeypatch.setattr(settings, "embedding_base_url", "http://127.0.0.1:11434")
    assert isinstance(build_embedding_provider(settings), OllamaEmbeddingProvider)


def test_hash_is_dependency_free_local_fallback(settings):
    embedder = LocalEmbeddingProvider()
    assert embedder.is_local is True
    assert len(embedder.embed_query("中文查询")) == 384


def test_cloud_embedding_requires_explicit_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cloud")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "secret-key")
    settings = Settings()
    assert isinstance(build_embedding_provider(settings), CloudEmbeddingProvider)


def test_cloud_embedding_sends_only_after_explicit_selection(settings, monkeypatch):
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=transport))
    provider = CloudEmbeddingProvider("https://embedding.example/v1", "key", "model")
    assert provider.embed_query("脱敏内容") == [1.0, 0.0]
    assert calls == [{"model": "model", "input": ["脱敏内容"]}]


async def test_vector_engine_keeps_contract_citations_and_security_gates(settings):
    secret = "password=Sup3rSecret!"
    (settings.wiki_dir / "projects" / "safe.md").write_text(
        f"# 安全页面\n{secret}\n差旅费用可以申请报销。", encoding="utf-8"
    )
    embedder = KeywordEmbedding()
    vector.build(settings, embedder)
    raw_index = vector.vector_index_path(settings).read_text(encoding="utf-8")
    assert secret not in raw_index
    assert "Sup3rSecret!" not in raw_index
    assert secret not in json.dumps(embedder.inputs, ensure_ascii=False)

    provider = FakeProvider("根据 [[projects/safe.md|安全页面]]：可以申请报销。")
    engine = VectorQuestionAnswerEngine(settings, embedder, min_score=0)
    result = await service.answer(
        settings, provider, "差旅怎么报销，联系 user@example.com", engine=engine
    )
    assert result == {
        "answer": "根据 [[projects/safe.md|安全页面]]：可以申请报销。",
        "citations": ["projects/safe.md"],
    }
    sent = json.dumps(provider.calls, ensure_ascii=False)
    assert "user@example.com" not in sent
    assert "[REDACTED:email]" in sent
    assert secret not in sent
    assert secret not in json.dumps([dict(row) for row in db.list_chat()], ensure_ascii=False)


async def test_vector_engine_empty_index_does_not_call_knowledge_model(settings):
    provider = FakeProvider("不应调用")
    engine = VectorQuestionAnswerEngine(settings, KeywordEmbedding(), auto_build=False)
    result = await engine.answer(provider, "任意问题")
    assert result == {"answer": "Wiki 中未找到相关内容。", "citations": []}
    assert provider.calls == []
