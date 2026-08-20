import os
from pathlib import Path

from app.config import Settings
from app.credentials.base import CredentialError, SecretPayload
from app.credentials.vaultwarden import VaultwardenAdapter

FAKE_BW = str(Path(__file__).parent / "fake_bw.py")


def _adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_BINARY", FAKE_BW)
    monkeypatch.setenv("BW_EMAIL", "u@example.com")
    monkeypatch.setenv("BW_PASSWORD", "master-pass")
    monkeypatch.setenv("BW_FAKE_STATE", str(tmp_path / "state.json"))
    s = Settings()
    s.bw_config_dir = str(tmp_path / "bwcfg")
    return VaultwardenAdapter(s)


async def test_create_and_list_metadata_only(tmp_path, monkeypatch):
    a = _adapter(tmp_path, monkeypatch)
    ref = await a.create_secret(SecretPayload(name="prod-db-password", value="Sup3rSecret!", note="订单服务"))
    assert ref.item_id
    metas = await a.list_items()
    assert metas[0].name == "prod-db-password"
    # 元数据绝不含秘密
    out = str(metas)
    assert "Sup3rSecret!" not in out


async def test_missing_bw_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_BINARY", "/nonexistent/bw")
    s = Settings()
    a = VaultwardenAdapter(s)
    assert a.available() is False
    try:
        await a.create_secret(SecretPayload(name="x", value="y"))
        assert False
    except CredentialError:
        pass


async def test_unconfigured_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_BINARY", FAKE_BW)
    monkeypatch.delenv("BW_EMAIL", raising=False)
    monkeypatch.delenv("BW_PASSWORD", raising=False)
    monkeypatch.delenv("BW_CLIENTID", raising=False)
    monkeypatch.delenv("BW_CLIENTSECRET", raising=False)
    s = Settings()
    a = VaultwardenAdapter(s)
    assert a.configured() is False
    try:
        await a.create_secret(SecretPayload(name="x", value="y"))
        assert False
    except CredentialError as e:
        assert "未配置" in str(e)


async def test_login_already_logged_in_tolerated(tmp_path, monkeypatch):
    """登录态已持久化（清理脚本等复用 bw 配置目录）时，login 报 already logged in 应容忍并继续解锁。"""
    a = _adapter(tmp_path, monkeypatch)
    calls = []

    async def fake_run(*args, stdin=None, timeout=90):
        calls.append(args)
        if args[:2] == ("login", "u@example.com"):
            raise CredentialError("You are already logged in as u@example.com.")
        if args[0] == "config":
            return ""
        if args[0] == "unlock":
            return "session-token"
        if args[0] == "get":
            return '{"type": 1, "name": "x"}'
        if args[0] == "encode":
            return "encoded"
        if args[0] == "create":
            return '{"id": "item-1"}'
        return ""

    monkeypatch.setattr(a, "_run", fake_run)
    ref = await a.create_secret(SecretPayload(name="x", value="y"))
    assert ref.item_id == "item-1"
    assert ("login", "u@example.com", "master-pass") in calls  # 尝试登录但失败被容忍
