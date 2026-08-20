"""OpenAICompatProvider.complete() 响应解析回归测试。

背景：deepseek-v4-flash 等推理模型会把 max_tokens 预算花在 reasoning_content 上，
content 可能为空（甚至为 null）。complete() 必须：
1) 容忍 content 缺失/为 null；
2) 仅返回推理内容时给出可操作的错误提示（增大 max_tokens / 换非推理模型）；
3) 正常情况返回去空白后的正文。
"""
import asyncio

import pytest

from app.llm.provider import LLMError, ModelConfig, OpenAICompatProvider

CFG = ModelConfig(
    id=1,
    name="t",
    provider_type="custom",
    base_url="http://127.0.0.1:9/v1",
    api_key="k",
    model="m",
)


class _FakeClient:
    """可替换响应体的 httpx.AsyncClient 替身。"""

    holder: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def post(self, *a, **k):
        resp = self.holder["resp"]
        resp.raise_for_status()
        return resp


class _Resp:
    def __init__(self, message):
        self._message = message

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": self._message}]}


def _run(message):
    _FakeClient.holder = {"resp": _Resp(message)}
    return asyncio.run(OpenAICompatProvider(CFG).complete("s", "u"))


def test_complete_returns_stripped_content(monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", _FakeClient)
    out = _run({"role": "assistant", "content": "  OK\n"})
    assert out == "OK"


def test_complete_empty_content_raises(monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", _FakeClient)
    with pytest.raises(LLMError, match="模型返回空内容"):
        _run({"role": "assistant", "content": ""})


def test_complete_missing_or_null_content_raises_cleanly(monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", _FakeClient)
    with pytest.raises(LLMError, match="模型返回空内容"):
        _run({"role": "assistant"})
    with pytest.raises(LLMError, match="模型返回空内容"):
        _run({"role": "assistant", "content": None})


def test_complete_reasoning_only_gives_actionable_error(monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", _FakeClient)
    with pytest.raises(LLMError, match="max_tokens"):
        _run({"role": "assistant", "content": "", "reasoning_content": "思考中……"})


def test_complete_content_wins_over_reasoning(monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.AsyncClient", _FakeClient)
    out = _run({"role": "assistant", "content": "OK", "reasoning_content": "思考"})
    assert out == "OK"
