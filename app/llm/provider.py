"""LLMProvider 抽象与适配器。业务代码只依赖 complete() 接口；
模型、地址、密钥全部来自页面配置（model_configs 表），代码不写死任何模型。

角色模型：
- knowledge：必配且每个角色至多激活一个，统一负责 Wiki 编译与知识问答；未配置时
  编译任务禁止提交、问答禁止发起（fail-closed）。
- security：可选增强检测器，接入 ScanEngine 本地检测（Regex → Context → Entropy）之后，
  只能新增或加严 Finding，失败时回退本地检测结果。仅允许 localhost/内网本地端点（禁止公网调用，
  无放开开关），扫描输入在 llm_detector 中等长掩码后才发送。
"""
import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .. import crypto, db
from ..config import Settings

ROLE_KNOWLEDGE = "knowledge"
ROLE_SECURITY = "security"
MODEL_ROLES = (ROLE_KNOWLEDGE, ROLE_SECURITY)


class LLMError(Exception):
    pass


PRESETS: dict[str, tuple[str, str, str]] = {
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    "glm": ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    "claude": ("Anthropic Claude", "https://api.anthropic.com/v1", "claude-sonnet-4-5"),
    "qwen": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "moonshot": ("Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "custom": ("自定义 OpenAI 兼容", "", ""),
}


@dataclass
class ModelConfig:
    id: int
    name: str
    provider_type: str
    base_url: str
    api_key: str
    model: str
    role: str = ROLE_KNOWLEDGE


class LLMProvider(Protocol):
    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 4000
    ) -> str: ...


class OpenAICompatProvider:
    """OpenAI 兼容网关：覆盖 OpenAI / DeepSeek / GLM / 通义 / Kimi / 任意兼容端点。"""

    def __init__(self, cfg: ModelConfig, timeout: float = 180) -> None:
        self.cfg = cfg
        self.timeout = timeout

    async def complete(self, system, user, *, json_mode=False, max_tokens=4000) -> str:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                content = msg.get("content") or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
            raise LLMError(f"模型请求失败: {type(e).__name__}: {str(e)[:300]}") from e
        content = str(content).strip()
        if not content:
            if msg.get("reasoning_content"):
                raise LLMError(
                    "模型未返回正文（仅输出推理内容）：推理模型可能把 max_tokens 全部花在思考上，"
                    "请增大 max_tokens 或改用非推理模型"
                )
            raise LLMError("模型返回空内容")
        return content


class AnthropicProvider:
    """Anthropic 原生 Messages API（Claude）。"""

    def __init__(self, cfg: ModelConfig, timeout: float = 180) -> None:
        self.cfg = cfg
        self.timeout = timeout

    async def complete(self, system, user, *, json_mode=False, max_tokens=4000) -> str:
        url = self.cfg.base_url.rstrip("/") + "/messages"
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.cfg.api_key:
            headers["x-api-key"] = self.cfg.api_key
        body = {
            "model": self.cfg.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=body, headers=headers)
                r.raise_for_status()
                blocks = r.json()["content"]
                content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            raise LLMError(f"模型请求失败: {type(e).__name__}: {str(e)[:300]}") from e
        if not content:
            raise LLMError("模型返回空内容")
        return content.strip()


# ---- security 角色端点策略：仅允许 localhost/内网本地端点，禁止公网调用 ----

def _host_is_local(host: str) -> bool:
    """host 是否为本地/内网。fail-closed：除 localhost 字面量外不信任任何域名后缀，
    主机名一律 DNS 解析并要求所有解析结果均为回环/私有/链路本地/保留地址
    （任一公网地址即拒绝，防 DNS 重绑定绕过）；无法解析即拒绝。"""
    h = (host or "").lower().strip("[]")
    if not h:
        return False
    if h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
    except socket.gaierror:
        return False
    addrs = {i[4][0].split("%")[0] for i in infos}
    if not addrs:
        return False
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved):
            return False
    return True


def validate_security_endpoint(base_url: str) -> str | None:
    """校验 security 角色端点；返回错误文案或 None。security 模型禁止公网调用：
    仅允许 localhost/内网本地端点，无任何放开开关（fail-closed）。"""
    host = urlsplit((base_url or "").strip()).hostname
    if not host:
        return "security 模型必须填写有效的 API 地址"
    if not _host_is_local(host):
        return "security 模型仅允许 localhost/内网本地端点（禁止公网调用），请配置本地部署的检测模型"
    return None


def build_provider(settings: Settings, row: dict, role: str | None = None) -> LLMProvider:
    role = role or row.get("role") or ROLE_KNOWLEDGE
    key = (
        crypto.open_sealed(settings.local_key(), row["api_key_enc"]).decode("utf-8")
        if row.get("api_key_enc")
        else ""
    )
    preset = PRESETS.get(row["provider_type"], ("", "", ""))
    base_url = row.get("base_url") or preset[1]
    if role == ROLE_SECURITY:
        err = validate_security_endpoint(base_url)
        if err:
            raise LLMError(err)
    cfg = ModelConfig(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=base_url,
        api_key=key,
        model=row.get("model") or preset[2],
        role=role,
    )
    if row["provider_type"] == "claude":
        return AnthropicProvider(cfg, settings.http_timeout)
    return OpenAICompatProvider(cfg, settings.http_timeout)


def get_active_provider(settings: Settings, role: str = ROLE_KNOWLEDGE) -> LLMProvider | None:
    """返回指定角色唯一激活的模型 Provider；未配置返回 None（调用方 fail-closed）。"""
    row = db.get_active_model_config(role)
    if not row:
        return None
    return build_provider(settings, dict(row), role=role)


def get_knowledge_provider(settings: Settings) -> LLMProvider | None:
    return get_active_provider(settings, ROLE_KNOWLEDGE)


def get_security_provider(settings: Settings) -> LLMProvider | None:
    """security 增强检测 Provider；端点策略不满足/配置损坏时视为未配置（回退本地检测）。"""
    try:
        return get_active_provider(settings, ROLE_SECURITY)
    except Exception as e:
        db.log_security(
            "security_model_unavailable",
            f"security 增强模型不可用，已回退本地检测: {type(e).__name__}: {str(e)[:200]}",
        )
        return None
