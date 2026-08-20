"""Vaultwarden 适配器：通过官方 bw CLI（Bitwarden CLI）操作，不直接读数据库。
登录凭证走环境变量（BW_EMAIL/BW_PASSWORD 或 BW_CLIENTID/BW_CLIENTSECRET）。
所有路径只返回元数据，绝不回显秘密值；错误信息中抹除秘密。"""
import asyncio
import json
import os
import shutil

from ..config import Settings
from .base import CredentialError, SecretMetadata, SecretPayload, SecretRef


class VaultwardenAdapter:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._session: str | None = None
        self._server_set = False
        self._busy = asyncio.Lock()

    def available(self) -> bool:
        return shutil.which(self.s.bw_binary) is not None

    def configured(self) -> bool:
        return bool((self.s.bw_email and self.s.bw_password) or (self.s.bw_clientid and self.s.bw_clientsecret))

    def _env(self, extra: dict | None = None) -> dict:
        env = dict(os.environ)
        env["BITWARDENCLI_APPDATA_DIR"] = self.s.bw_config_dir
        env.pop("BW_SESSION", None)
        if self._session:
            env["BW_SESSION"] = self._session
        if self.s.bw_password:
            env["BW_PASSWORD"] = self.s.bw_password
        if self.s.bw_clientid:
            env["BW_CLIENTID"] = self.s.bw_clientid
        if self.s.bw_clientsecret:
            env["BW_CLIENTSECRET"] = self.s.bw_clientsecret
        if extra:
            env.update(extra)
        return env

    def _redact(self, s: str) -> str:
        for secret in (self.s.bw_password, self.s.bw_clientsecret):
            if secret:
                s = s.replace(secret, "***")
        return s

    async def _run(self, *args: str, stdin: str | None = None, timeout: int = 90) -> str:
        if not self.available():
            raise CredentialError("bw CLI 未安装（Docker 镜像内置，本机开发可 brew install bitwarden-cli）")
        try:
            proc = await asyncio.create_subprocess_exec(
                self.s.bw_binary,
                *args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
            )
        except (FileNotFoundError, OSError) as e:
            raise CredentialError("bw CLI 无法执行") from e
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin else None), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise CredentialError("bw CLI 超时")
        if proc.returncode != 0:
            raise CredentialError(self._redact(err.decode(errors="replace").strip()[:500]))
        return out.decode(errors="replace")

    async def _ensure_ready(self) -> None:
        if self._session:
            return
        if not self._server_set:
            try:
                await self._run("config", "server", self.s.vaultwarden_url)
            except CredentialError as e:
                # 之前残留登录态时 bw 拒绝改 server：先登出再配置
                if "Logout required" in str(e):
                    try:
                        await self._run("logout")
                    except CredentialError:
                        pass
                    await self._run("config", "server", self.s.vaultwarden_url)
                else:
                    raise
            self._server_set = True
        if self.s.bw_clientid and self.s.bw_clientsecret:
            await self._run("login", "--apikey")
            self._session = (await self._run("unlock", "--apikey", "--raw")).strip()
        elif self.s.bw_email and self.s.bw_password:
            try:
                await self._run("login", self.s.bw_email, self.s.bw_password)
            except CredentialError as e:
                # 登录态已持久化（如清理脚本复用 bw 配置目录）时容忍：直接解锁
                if "already logged in" not in str(e):
                    raise
            self._session = (await self._run("unlock", "--passwordenv", "BW_PASSWORD", "--raw")).strip()
        else:
            raise CredentialError("未配置 Vaultwarden 登录凭证（BW_EMAIL/BW_PASSWORD 或 BW_CLIENTID/BW_CLIENTSECRET）")
        if not self._session:
            raise CredentialError("Vaultwarden 解锁失败")

    async def create_secret(self, payload: SecretPayload) -> SecretRef:
        async with self._busy:
            try:
                return await self._create(payload)
            except CredentialError:
                self._session = None  # 会话失效时重新登录重试一次
                return await self._create(payload)

    async def _create(self, payload: SecretPayload) -> SecretRef:
        await self._ensure_ready()
        tpl = await self._run("get", "template", "item")
        item = json.loads(tpl)
        item["type"] = 1
        item["name"] = payload.name
        item["notes"] = payload.note or ""
        item["login"] = {"username": None, "password": payload.value, "uris": [], "totp": None}
        encoded = (await self._run("encode", stdin=json.dumps(item, ensure_ascii=False))).strip()
        created = await self._run("create", "item", encoded)
        data = json.loads(created)
        item_id = data.get("id") or ""
        if not item_id:
            raise CredentialError("Vaultwarden 未返回条目 ID")
        return SecretRef(provider="vaultwarden", name=payload.name, item_id=item_id)

    async def list_items(self) -> list[SecretMetadata]:
        async with self._busy:
            try:
                return await self._list_items()
            except CredentialError:
                self._session = None  # 会话失效（如 Vaultwarden 重启）时重新登录重试
                return await self._list_items()

    async def _list_items(self) -> list[SecretMetadata]:
        await self._ensure_ready()
        out = await self._run("list", "items")
        try:
            items = json.loads(out or "[]")
        except json.JSONDecodeError as e:
            raise CredentialError("Vaultwarden 返回异常") from e
        metas = []
        for it in items:
            login = it.get("login") or {}
            uris = login.get("uris") or []
            uri = uris[0].get("uri", "") if uris else ""
            metas.append(
                SecretMetadata(
                    name=it.get("name") or "",
                    item_id=it.get("id") or "",
                    note=(login.get("username") or "") + (" · " + uri if uri else ""),
                    updated_at=it.get("revisionDate") or "",
                )
            )
        return metas

    async def get_metadata(self, ref: SecretRef) -> SecretMetadata:
        for m in await self.list_items():
            if m.item_id == ref.item_id:
                return m
        raise CredentialError("条目不存在")

    async def update_secret(self, ref: SecretRef, patch: dict) -> SecretRef:
        async with self._busy:
            await self._ensure_ready()
            item = json.loads(await self._run("get", "item", ref.item_id))
            if "name" in patch:
                item["name"] = patch["name"]
            if "value" in patch:
                item.setdefault("login", {})["password"] = patch["value"]
            if "note" in patch:
                item["notes"] = patch["note"]
            encoded = (await self._run("encode", stdin=json.dumps(item, ensure_ascii=False))).strip()
            await self._run("edit", "item", ref.item_id, encoded)
            return SecretRef(provider="vaultwarden", name=patch.get("name", ref.name), item_id=ref.item_id)

    async def delete_secret(self, ref: SecretRef) -> None:
        async with self._busy:
            await self._ensure_ready()
            await self._run("delete", "item", ref.item_id)
