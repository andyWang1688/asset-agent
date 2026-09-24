from llama_index.core.bridge.pydantic import ConfigDict
from llama_index.core.embeddings import BaseEmbedding
from typing import ClassVar

from app.credentials.base import CredentialError, SecretMetadata, SecretRef
from app.llm.provider import LLMProvider


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def complete(self, system, user, *, json_mode=False, max_tokens=4000) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response


class SequenceProvider:
    """按顺序返回响应（用于 LLM 工具循环测试）；耗尽后抛错。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, system, user, *, json_mode=False, max_tokens=4000) -> str:
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise RuntimeError("SequenceProvider 响应耗尽")
        return self.responses.pop(0)


class StreamingSequenceProvider(SequenceProvider):
    """带流式能力的脚本 Provider：正文按脚本返回，推理增量固定上抛。"""

    def __init__(self, responses, reasoning=("思考片段",)):
        super().__init__(responses)
        self.reasoning = list(reasoning)

    async def stream_complete(self, system, user, *, json_mode=False, max_tokens=4000, on_reasoning=None):
        self.calls.append({"system": system, "user": user})
        if on_reasoning is not None:
            for piece in self.reasoning:
                await on_reasoning(piece)
        if not self.responses:
            raise RuntimeError("SequenceProvider 响应耗尽")
        return self.responses.pop(0)


class FakeCredentialStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created = []

    async def create_secret(self, payload):
        if self.fail:
            raise CredentialError("vault down")
        self.created.append(payload)
        return SecretRef(provider="fake", name=payload.name, item_id=f"vw-{len(self.created)}")

    async def list_items(self):
        return [
            SecretMetadata(name=p.name, item_id=f"vw-{i + 1}", updated_at="2026-08-15T00:00:00Z")
            for i, p in enumerate(self.created)
        ]

    async def update_secret(self, ref, patch):
        return ref

    async def get_metadata(self, ref):
        return SecretMetadata(name=ref.name, item_id=ref.item_id)

    async def delete_secret(self, ref):
        pass

    def available(self):
        return True

    def configured(self):
        return True


class KeywordEmbedding(BaseEmbedding):
    """确定性本地 embedding 测试替身（LlamaIndex BaseEmbedding 子类，不加载任何模型）。"""

    model_name: str = "fixture-keywords"
    is_local: ClassVar[bool] = True
    model_config = ConfigDict(extra="allow")

    def __init__(self, **kwargs):
        super().__init__(model_name="fixture-keywords", **kwargs)
        self.inputs: list[str] = []

    def _vec(self, text: str) -> list[float]:
        value = str(text)
        return [
            1.0 if "报销" in value or "差旅" in value else 0.0,
            1.0 if "订单" in value else 0.0,
            1.0 if "缓存" in value else 0.0,
            0.1,
        ]

    def _get_text_embedding(self, text: str) -> list[float]:
        self.inputs.append(text)
        return self._vec(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vec(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)


class FixturePlanningProvider(FakeProvider):
    """每轮创建独立测试页面，避免重复测试夹具覆盖已有页面。"""
    def __init__(self):
        import json
        from app import db
        task = db.list_tasks()[0]
        plan = {'source_summary': {'path': f"sources/fixture-{task['id']}.md", 'title': '测试资料',
                                   'content': '# 测试资料\n已整理。'}, 'pages': [], 'conflicts': []}
        super().__init__(json.dumps({'action': 'final', 'plan': plan}))


async def finish_queued(settings, creds, result):
    """测试显式推进后台流程；生产 ingest 不等待模型与保存。"""
    from app import db
    from app.worker import Worker
    if result.get('task_id') and db.get_task(result['task_id'])['status'] == 'planning_pending':
        await Worker(settings, creds, lambda: FixturePlanningProvider(), lambda: None).tick()
        task = db.get_task(result['task_id'])
        assert task['status'] == 'done', task['error']
        result['source_id'] = task['source_id']
        report = db.report_view(result['report_id'])
        result['secrets'] = [{'name': e['name'], 'saved': e['vault']['saved']} for e in report['entries'] if e['action'] == 'store']
    return result


async def ingest_and_finish(settings, creds, **kwargs):
    from app.ingest import receiver
    return await finish_queued(settings, creds, await receiver.ingest(settings, creds, **kwargs))
