"""混合检索 + 重排（issue #13）：LlamaIndex 固定语料召回对比、重排开关、契约与安全回归。"""

import json

import pytest
from fastapi.testclient import TestClient
from llama_index.core.bridge.pydantic import ConfigDict
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import QueryBundle

from app import db, main
from app.config import Settings
from app.query import hybrid, retrieval, service
from app.query.embeddings import EmbeddingError, LazyHuggingFaceEmbedding
from tests.fakes import FakeCredentialStore, FakeProvider


# 固定语料：每页一个语义概念；concepts 维度模拟语义 embedding 的语义映射。
CONCEPTS = [
    ("报销", "差旅", "出差", "费用", "买票", "钱", "要回来", "拿回来"),
    ("订单", "下单", "购物", "购买", "买东西"),
    ("缓存", "Redis"),
    ("部署", "上线", "发布"),
]


class ConceptEmbedding(BaseEmbedding):
    """语义映射测试替身（LlamaIndex BaseEmbedding 子类，不加载真实模型）。"""

    model_name: str = "test-concepts"
    model_config = ConfigDict(extra="allow")

    def __init__(self, **kwargs):
        super().__init__(model_name="test-concepts", **kwargs)
        self.inputs: list[str] = []

    def _vec(self, text: str) -> list[float]:
        row = [0.0] * (len(CONCEPTS) + 1)
        for index, triggers in enumerate(CONCEPTS):
            if any(trigger in text for trigger in triggers):
                row[index] = 1.0
        row[-1] = 0.1
        return row

    def _get_text_embedding(self, text: str) -> list[float]:
        self.inputs.append(text)
        return self._vec(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vec(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)


CORPUS = {
    "concepts/expense.md": "# 报销制度\n员工因公出差产生的费用可以申请报销，差旅费按月结算。\n",
    "concepts/orders.md": "# 订单服务\n订单提交后写入缓存，查询订单直接读缓存。\n",
    "concepts/deploy.md": "# 发布流程\n新版本上线前先构建镜像，再滚动发布。\n",
    "projects/ci.md": "# CI 流水线\n每次推送自动跑测试，红灯不让合并。\n",
    "concepts/git.md": "# Git 规范\n提交信息一行说清楚，分支以 codex/ 开头。\n",
}

QUERIES = [
    ("怎么申请报销", "concepts/expense.md"),
    ("订单服务的缓存", "concepts/orders.md"),
    ("怎么发布新版本", "concepts/deploy.md"),
    ("买东西的流程是什么", "concepts/orders.md"),   # 语义：与目标页无共同词
    ("坐车办事花的钱怎么拿回来", "concepts/expense.md"),  # 语义：与目标页无共同词
]


def _write_corpus(settings):
    for path, content in CORPUS.items():
        page = settings.wiki_dir / path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content)


def _top_paths(hits):
    return [hit["path"] for hit in hits if hit.get("path")]


def test_hybrid_recall_hits_all_fixed_corpus_queries(settings):
    """固定语料召回：关键词与语义改写问句都在 top-3 命中目标页（对等切换前基线）。"""
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    retrieval.build(settings, embedder)
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=embedder, limit=3)

    for question, target in QUERIES:
        paths = _top_paths(engine.retrieve(question))
        assert target in paths, f"混合召回未命中目标页 {target}: {question}"


def test_keyword_branch_recalls_page_without_semantic_support(settings):
    """关键词支路（BM25）：语义支路不给力时，关键词页仍被召回；零分页被丢弃。"""
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    retrieval.build(settings, embedder)

    def dead(query):
        return [0.0] * (len(CONCEPTS)) + [1e-9]

    embedder._get_query_embedding = dead  # 语义支路退化为均匀分数：只靠 BM25 命中
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=embedder, limit=3)
    assert "concepts/orders.md" in _top_paths(engine.retrieve("订单缓存"))

    # 关键词支路单独看：只返回真实匹配页，零分页不进 RRF 融合。
    index = retrieval.load_index(settings, embedder)
    bm25 = hybrid.NonZeroBM25Retriever.from_defaults(
        docstore=index.docstore,
        similarity_top_k=5,
        token_pattern=retrieval.BM25_TOKEN_PATTERN,
    )
    assert [n.node.metadata["path"] for n in bm25.retrieve("订单缓存")] == ["concepts/orders.md"]


async def test_hybrid_engine_keeps_contract_citations_and_security_gates(settings):
    secret = "password=Sup3rSecret!"
    (settings.wiki_dir / "projects" / "safe.md").write_text(
        f"# 安全页面\n{secret}\n差旅费用可以申请报销。", encoding="utf-8"
    )
    embedder = ConceptEmbedding()
    retrieval.build(settings, embedder)
    # 秘密原文不进索引持久层（LlamaIndex SimpleVectorStore JSON）
    for file in retrieval.index_dir(settings).rglob("*.json"):
        assert secret not in file.read_text(encoding="utf-8")
    assert secret not in json.dumps(embedder.inputs, ensure_ascii=False)

    provider = FakeProvider("根据 [[projects/safe.md|安全页面]]：可以申请报销。")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=embedder)
    result = await service.answer(
        settings, provider, "差旅怎么报销，联系 user@example.com", engine=engine
    )
    assert result == {
        "answer": "根据 [[projects/safe.md|安全页面]]：可以申请报销。",
        "citations": ["projects/safe.md"],
        "semantic_retrieval_enabled": True,
    }
    sent = json.dumps(provider.calls, ensure_ascii=False)
    assert "user@example.com" not in sent
    assert "[REDACTED:email]" in sent
    assert secret not in sent
    assert secret not in json.dumps([dict(row) for row in db.list_chat()], ensure_ascii=False)


async def test_hybrid_engine_empty_index_does_not_call_knowledge_model(settings):
    provider = FakeProvider("不应调用")
    engine = hybrid.HybridQuestionAnswerEngine(settings, ConceptEmbedding(), auto_build=False)
    result = await engine.answer(provider, "任意问题")
    assert result == {"answer": "Wiki 中未找到相关内容。", "citations": [], "semantic_retrieval_enabled": False}
    assert provider.calls == []


def _first_page_in_prompt(provider):
    return provider.calls[0]["user"].split("## 页面: [[")[1].split("|")[0]


async def test_reranker_off_returns_pure_recall_order(settings):
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    retrieval.build(settings, embedder)
    provider = FakeProvider("回答")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=embedder)  # 不装配重排器 = 停用
    await engine.answer(provider, "订单服务的缓存怎么做")
    assert _first_page_in_prompt(provider) == "concepts/orders.md"


class FakeReranker(BaseNodePostprocessor):
    """LlamaIndex 后处理节点测试替身：把 expense 页提到最前。"""

    def _postprocess_nodes(self, nodes, query_bundle: QueryBundle | None = None):
        return sorted(nodes, key=lambda n: n.node.metadata.get("path") != "concepts/expense.md")


async def test_reranker_reorders_candidates(settings):
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    retrieval.build(settings, embedder)
    provider = FakeProvider("回答")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=embedder, reranker=FakeReranker())
    await engine.answer(provider, "订单服务的缓存怎么做")
    assert _first_page_in_prompt(provider) == "concepts/expense.md"


def test_build_reranker_respects_settings_mode(settings, monkeypatch):
    monkeypatch.setattr(settings, "reranker", "off")
    assert hybrid.build_reranker(settings) is None

    class FakeST:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(hybrid, "SentenceTransformerRerank", FakeST)
    monkeypatch.setattr(settings, "reranker", "local")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-base")
    built = hybrid.build_reranker(settings, top_n=3)
    assert isinstance(built, FakeST)
    assert built.kwargs["model"] == "BAAI/bge-reranker-base"
    assert built.kwargs["top_n"] == 3

    monkeypatch.setattr(settings, "reranker", "unknown")
    with pytest.raises(EmbeddingError):
        hybrid.build_reranker(settings)


def test_reranker_setting_defaults_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("RERANKER", "off")
    assert Settings().reranker == "off"
    monkeypatch.delenv("RERANKER")
    assert Settings().reranker == "local"
    assert Settings().reranker_model == "BAAI/bge-reranker-base"


def test_default_embedding_is_lazy_local_bge(settings):
    from app.query.embeddings import build_embedding_provider

    embedder = build_embedding_provider(settings)
    assert isinstance(embedder, LazyHuggingFaceEmbedding)
    assert embedder.model_name == "BAAI/bge-small-zh-v1.5"
    assert embedder.is_local is True


def test_hybrid_engine_selected_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))

    with TestClient(main.app) as client:
        engine = main.app.state.ctx.get_query_engine()
        assert isinstance(engine, hybrid.HybridQuestionAnswerEngine)
        response = client.post("/api/query", json={"question": "测试问题"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Wiki 中未找到相关内容。",
        "citations": [],
        "semantic_retrieval_enabled": False,
    }


def test_default_engine_is_hybrid(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))

    with TestClient(main.app) as client:
        assert isinstance(main.app.state.ctx.get_query_engine(), hybrid.HybridQuestionAnswerEngine)


class BrokenEmbedding(ConceptEmbedding):
    """模型被移除/损坏的替身：任何 embedding 调用都抛错（夹具模拟，不加载真实模型）。"""

    def _get_text_embedding(self, text: str) -> list[float]:
        raise OSError("model weights missing")

    def _get_query_embedding(self, query: str) -> list[float]:
        raise OSError("model weights missing")

    async def _aget_text_embedding(self, text: str) -> list[float]:
        raise OSError("model weights missing")

    async def _aget_query_embedding(self, query: str) -> list[float]:
        raise OSError("model weights missing")


async def test_answer_degrades_to_keyword_when_model_broken(settings):
    """模型损坏后提问：纯关键词召回 + 降级标志，不报错（索引已建、查询时 embedding 失败）。"""
    _write_corpus(settings)
    retrieval.build(settings, ConceptEmbedding())
    engine = hybrid.HybridQuestionAnswerEngine(settings, embed_model=BrokenEmbedding(), limit=3, auto_build=False)
    provider = FakeProvider("回答")

    result = await engine.answer(provider, "订单缓存", history=None)

    assert result["semantic_retrieval_enabled"] is False
    assert "concepts/orders.md" in result["citations"]
    assert provider.calls  # 关键词召回命中后仍进入知识库模型渲染


async def test_service_answer_degrades_when_index_build_fails(settings, monkeypatch):
    """模型被移除、索引无法构建：service 层同样降级为关键词召回 + 标志，不抛错。"""
    (settings.wiki_dir / "projects" / "demo.md").write_text(
        "# Demo\nDemo 项目介绍，包含订单服务。", encoding="utf-8"
    )
    from app.query import hybrid as hybrid_mod
    from app.query import retrieval as retrieval_mod

    broken = BrokenEmbedding()
    monkeypatch.setattr(hybrid_mod, "build_embedding_provider", lambda s: broken)
    monkeypatch.setattr(retrieval_mod, "build_embedding_provider", lambda s: broken)
    provider = FakeProvider("根据 [[projects/demo.md|Demo]]：说明。")

    result = await service.answer(settings, provider, "订单服务是什么")

    assert result["semantic_retrieval_enabled"] is False
    assert result["citations"] == ["projects/demo.md"]
