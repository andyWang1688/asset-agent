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
