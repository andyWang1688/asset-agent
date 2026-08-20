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
