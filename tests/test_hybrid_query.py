"""混合检索 + 重排（issue #9）：固定语料召回对比、重排开关、契约与安全回归。"""

import json

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.config import Settings
from app.query import bm25, hybrid, index as file_index, service, vector
from app.query.embeddings import EmbeddingError, EmbeddingProvider
from tests.fakes import FakeCredentialStore, FakeProvider


# 固定语料：每页一个语义概念；concepts 维度模拟语义 embedding 的语义映射。
CONCEPTS = [
    ("报销", "差旅", "出差", "费用", "买票", "钱", "要回来", "拿回来"),
    ("订单", "下单", "购物", "购买", "买东西"),
    ("缓存", "Redis"),
    ("部署", "上线", "发布"),
]


class ConceptEmbedding(EmbeddingProvider):
    name = "test-concepts"
    model = "fixture"
    is_local = True

    def __init__(self):
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        vectors = []
        for text in texts:
            row = [0.0] * (len(CONCEPTS) + 1)
            for index, triggers in enumerate(CONCEPTS):
                if any(trigger in text for trigger in triggers):
                    row[index] = 1.0
            row[-1] = 0.1
            vectors.append(row)
        return vectors


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
        page.write_text(content, encoding="utf-8")


def _top_paths(hits):
    return [hit["path"] for hit in hits if hit.get("path")]


def test_bm25_ranks_keyword_page_first():
    pages = [
        {"path": "concepts/orders.md", "title": "订单服务", "content": "订单提交后写入缓存。"},
        {"path": "concepts/expense.md", "title": "报销制度", "content": "出差费用按月报销。"},
    ]
    hits = bm25.search(pages, "订单缓存", limit=2)
    assert _top_paths(hits) == ["concepts/orders.md"]
    assert hits[0]["bm25"] > 0
    assert bm25.search(pages, "不存在的词汇xyz", limit=2) == []


def test_hybrid_recall_not_below_fts5_baseline(settings):
    """固定语料召回对比：语义与关键词问句都命中目标页，且不低于 FTS5 基线。"""
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    vector.build(settings, embedder)
    file_index.build(settings)  # 同步 SQLite 页表，供 FTS5 基线检索

    hybrid_hits = fts5_hits = 0
    for question, target in QUERIES:
        fts5_paths = _top_paths(db.search_pages(question, limit=5))
        hybrid_paths = _top_paths(
            hybrid.recall(settings, question, limit=5, embedding_provider=embedder)
        )
        assert target in hybrid_paths, f"混合召回未命中目标页 {target}: {question}"
        fts5_hits += int(target in fts5_paths)
        hybrid_hits += int(target in hybrid_paths)

    assert hybrid_hits == len(QUERIES)
    assert hybrid_hits >= fts5_hits  # 不低于 FTS5 基线
    assert hybrid_hits > fts5_hits  # 语义问句只有混合召回能命中


async def test_hybrid_engine_keeps_contract_citations_and_security_gates(settings):
    secret = "password=Sup3rSecret!"
    (settings.wiki_dir / "projects" / "safe.md").write_text(
        f"# 安全页面\n{secret}\n差旅费用可以申请报销。", encoding="utf-8"
    )
    embedder = ConceptEmbedding()
    vector.build(settings, embedder)
    raw_index = vector.vector_index_path(settings).read_text(encoding="utf-8")
    assert secret not in raw_index
    assert "Sup3rSecret!" not in raw_index
    assert secret not in json.dumps(embedder.inputs, ensure_ascii=False)

    provider = FakeProvider("根据 [[projects/safe.md|安全页面]]：可以申请报销。")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embedder, min_score=0)
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


async def test_hybrid_engine_empty_index_does_not_call_knowledge_model(settings):
    provider = FakeProvider("不应调用")
    engine = hybrid.HybridQuestionAnswerEngine(settings, ConceptEmbedding(), auto_build=False)
    result = await engine.answer(provider, "任意问题")
    assert result == {"answer": "Wiki 中未找到相关内容。", "citations": []}
    assert provider.calls == []


def _first_page_in_prompt(provider):
    return provider.calls[0]["user"].split("## 页面: [[")[1].split("|")[0]


async def test_reranker_off_returns_pure_recall_order(settings):
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    vector.build(settings, embedder)
    provider = FakeProvider("回答")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embedder)  # 不装配重排器 = 停用
    await engine.answer(provider, "订单服务的缓存怎么做")
    assert _first_page_in_prompt(provider) == "concepts/orders.md"


async def test_reranker_reorders_candidates(settings):
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    vector.build(settings, embedder)

    def reranker(question, candidates):
        return sorted(candidates, key=lambda c: c["path"] != "concepts/expense.md")

    provider = FakeProvider("回答")
    engine = hybrid.HybridQuestionAnswerEngine(settings, embedder, reranker=reranker, min_score=0)
    await engine.answer(provider, "订单服务的缓存怎么做")
    assert _first_page_in_prompt(provider) == "concepts/expense.md"


def test_local_reranker_weights_fusion_and_similarity(settings):
    _write_corpus(settings)
    embedder = ConceptEmbedding()
    vector.build(settings, embedder)
    hits = hybrid.recall(settings, "订单缓存", limit=5, embedding_provider=embedder)
    reranked = hybrid.LocalReranker(embedder)("订单缓存", hits)
    assert reranked[0]["path"] == "concepts/orders.md"
    assert {c["path"] for c in reranked} == {c["path"] for c in hits}


def test_build_reranker_respects_settings_mode(settings, monkeypatch):
    embedder = ConceptEmbedding()
    monkeypatch.setattr(settings, "reranker", "off")
    assert hybrid.build_reranker(settings, embedder) is None
    monkeypatch.setattr(settings, "reranker", "local")
    assert isinstance(hybrid.build_reranker(settings, embedder), hybrid.LocalReranker)
    monkeypatch.setattr(settings, "reranker", "unknown")
    with pytest.raises(EmbeddingError):
        hybrid.build_reranker(settings, embedder)


def test_reranker_setting_defaults_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("RERANKER", "off")
    assert Settings().reranker == "off"
    monkeypatch.delenv("RERANKER")
    assert Settings().reranker == "local"


def test_hybrid_engine_selected_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("QUERY_ENGINE", "hybrid")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))

    with TestClient(main.app) as client:
        engine = main.app.state.ctx.get_query_engine()
        assert isinstance(engine, hybrid.HybridQuestionAnswerEngine)
        response = client.post("/api/query", json={"question": "测试问题"})

    assert response.status_code == 200
    assert response.json() == {"answer": "Wiki 中未找到相关内容。", "citations": []}


def test_default_engine_is_hybrid(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))

    with TestClient(main.app) as client:
        assert isinstance(main.app.state.ctx.get_query_engine(), hybrid.HybridQuestionAnswerEngine)


def test_engine_rollback_to_fts5_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("QUERY_ENGINE", "fts5")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("回答"))

    with TestClient(main.app) as client:
        from app.query.engine import FTS5QuestionAnswerEngine

        assert isinstance(main.app.state.ctx.get_query_engine(), FTS5QuestionAnswerEngine)
