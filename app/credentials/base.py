"""凭证库抽象。约束：只写、只读元数据，不向业务/LLM 流程提供读取秘密原文的能力。"""
from dataclasses import dataclass, field
from typing import Any, Protocol


class CredentialError(Exception):
    """凭证库不可用或操作失败。"""


@dataclass
class SecretPayload:
    name: str
    value: str
    kind: str = "login"
    note: str = ""
    username: str | None = None
    uri: str | None = None
    # Secure Note 的字段：[(字段名, 字段值)]；kind == "secure_note" 时使用
    fields: list = field(default_factory=list)


@dataclass
class SecretRef:
    provider: str = "vaultwarden"
    name: str = ""
    item_id: str = ""
    field_name: str = ""


@dataclass
class SecretMetadata:
    name: str
    item_id: str
    note: str = ""
    updated_at: str = ""
    provider: str = "vaultwarden"
    kind: str = "login"
    # 内部幂等匹配用（从应用管理的 note 中提取），不作为对外公开元数据
    transaction_id: str = ""
    value_hash: str = ""
    field_name: str = ""


class CredentialStore(Protocol):
    async def create_secret(self, payload: SecretPayload) -> SecretRef: ...
    async def update_secret(self, ref: SecretRef, patch: dict[str, Any]) -> SecretRef: ...
    async def get_metadata(self, ref: SecretRef) -> SecretMetadata: ...
    async def delete_secret(self, ref: SecretRef) -> None: ...
    async def list_items(self) -> list[SecretMetadata]: ...
