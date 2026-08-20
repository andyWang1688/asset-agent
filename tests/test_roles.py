"""模型角色拆分测试：knowledge/security 双角色、必配闸门、端点策略、安全增强检测层。"""
import json
import socket

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.ingest import receiver
from app.llm import provider as llm
from app.security.detectors import ScanEngine
from app.security.policy import default_policy
from app.security.rules import KIND_CREDENTIAL, KIND_UNKNOWN
from tests.fakes import FakeCredentialStore, FakeProvider

SECRET = "Sup3rSecret!"


class BrokenSecurityProvider:
    async def complete(self, *a, **k):
        raise RuntimeError("security model down")


# ---- schema/migration ----

def test_legacy_table_migrated_with_role(workspace):
    """老库 model_configs 无 role 列（也无部分唯一索引）：迁移补列且历史配置归为 knowledge。"""
    db._w("INSERT INTO model_configs(name,provider_type,base_url,api_key_enc,model,is_active) "
          "VALUES('legacy','deepseek','','enc','m',1)")
    db._w("DROP INDEX IF EXISTS idx_model_configs_active_role")  # 老库本无该索引
    db._w("ALTER TABLE model_configs DROP COLUMN role")
    db._migrate()
    rows = db.list_model_configs()
    assert rows[0]["role"] == "knowledge"
    assert rows[0]["is_active"] == 1  # 迁移保留激活状态
    idx = [r["name"] for r in db._r("PRAGMA index_list(model_configs)")]
    assert "idx_model_configs_active_role" in idx  # 索引已重建


# ---- Provider 查询接口与端点策略 ----

def test_provider_api_key_decoded_to_str(workspace, settings):
    """解密后的 api_key 必须是 str：bytes 会以 b'...' 形式拼进 Bearer 头导致 401。"""
    from app import crypto

    key = "sk-test1234567890abcdef"
    enc = crypto.seal(settings.local_key(), key.encode())
    db.upsert_model_config(None, "k", "custom", "http://127.0.0.1:9001/v1", enc, "m1", True, "knowledge")
    p = llm.get_knowledge_provider(settings)
    assert isinstance(p.cfg.api_key, str)
    assert p.cfg.api_key == key
    assert f"Bearer {p.cfg.api_key}" == f"Bearer {key}"
    assert "b'" not in p.cfg.api_key


def test_provider_role_selection(workspace, settings):
    db.upsert_model_config(None, "k", "custom", "http://127.0.0.1:9001/v1", "", "m1", True, "knowledge")
    db.upsert_model_config(None, "s", "custom", "http://127.0.0.1:9001/v1", "", "m2", True, "security")
    assert llm.get_knowledge_provider(settings).cfg.model == "m1"
    assert llm.get_security_provider(settings).cfg.model == "m2"
    # 未配置角色 → None（fail-closed）
    assert llm.get_active_provider(settings, "no_such_role") is None


def test_endpoint_policy_literal_ips(settings):
    assert llm.validate_security_endpoint("https://8.8.8.8/v1") is not None
    assert llm.validate_security_endpoint("https://1.1.1.1:8443/v1") is not None
    assert llm.validate_security_endpoint("http://127.0.0.1:9001/v1") is None
    assert llm.validate_security_endpoint("http://localhost:9001/v1") is None
    assert llm.validate_security_endpoint("http://[::1]:9001/v1") is None
    assert llm.validate_security_endpoint("http://10.1.2.3:8080/v1") is None
    assert llm.validate_security_endpoint("http://192.168.0.10:9001/v1") is None
    assert llm.validate_security_endpoint("http://172.16.5.5/v1") is None
    assert llm.validate_security_endpoint("not-a-url") is not None


def test_endpoint_policy_no_suffix_passthrough(settings, monkeypatch):
    """域名后缀不得直通：.local/.internal/.localhost 等必须解析为本地地址才放行。"""
    def fake_getaddrinfo(host, port):
        if host in ("model.internal", "local-model.corp", "printer.local"):
            return [(2, 1, 6, "", ("10.1.1.9", 0))]
        if host in ("evil.internal", "evil.local", "evil.localhost"):
            return [(2, 1, 6, "", ("8.8.4.4", 0))]
        raise socket.gaierror("无法解析")

    monkeypatch.setattr(llm.socket, "getaddrinfo", fake_getaddrinfo)
    # 后缀名解析到内网地址 → 允许（不依赖后缀直通）
    assert llm.validate_security_endpoint("http://model.internal:9001/v1") is None
    assert llm.validate_security_endpoint("http://printer.local:9001/v1") is None
    # 后缀名解析到公网地址 → 拒绝（后缀本身不再放行）
    assert llm.validate_security_endpoint("http://evil.internal/v1") is not None
    assert llm.validate_security_endpoint("http://evil.local/v1") is not None
    assert llm.validate_security_endpoint("http://evil.localhost/v1") is not None
    # 无法解析 → 拒绝（fail-closed）
    assert llm.validate_security_endpoint("http://unresolvable.local/v1") is not None


def test_endpoint_policy_hostnames(settings, monkeypatch):
    def fake_getaddrinfo(host, port):
        if host == "local-model.corp":
            return [(2, 1, 6, "", ("10.1.1.9", 0))]
        if host == "mixed.example.com":
            return [(2, 1, 6, "", ("10.1.1.9", 0)), (2, 1, 6, "", ("8.8.4.4", 0))]
        if host == "public.example.com":
            return [(2, 1, 6, "", ("8.8.4.4", 0))]
        raise socket.gaierror("无法解析")

    monkeypatch.setattr(llm.socket, "getaddrinfo", fake_getaddrinfo)
    assert llm.validate_security_endpoint("http://local-model.corp:9001/v1") is None
    assert llm.validate_security_endpoint("http://public.example.com/v1") is not None
    assert llm.validate_security_endpoint("http://mixed.example.com/v1") is not None  # 任一分辨结果为公网即拒绝
    assert llm.validate_security_endpoint("http://unresolvable.host/v1") is not None


def test_endpoint_policy_no_public_override(settings):
    """security 模型禁止公网调用：不存在任何放开开关。"""
    assert llm.validate_security_endpoint("https://8.8.8.8/v1") is not None


def test_security_provider_public_endpoint_unavailable(workspace, settings):
    db.upsert_model_config(None, "s", "custom", "https://8.8.8.8/v1", "", "m2", True, "security")
    assert llm.get_security_provider(settings) is None  # 回退本地检测
    assert any(e["kind"] == "security_model_unavailable" for e in db.list_security())


# ---- ScanEngine 安全增强层 ----

async def test_security_layer_adds_finding(settings):
    text = "普通内容 mocksecret 与说明"
    s = text.index("mocksecret")
    resp = json.dumps(
        {"findings": [{"span": [s, s + len("mocksecret")], "kind": "credential",
                       "confidence": 0.6, "evidence": "mock 命中"}]},
        ensure_ascii=False,
    )
    provider = FakeProvider(resp)
    findings = await ScanEngine(default_policy(), security_provider=provider).scan_async(text)
    f = next((x for x in findings if x.rule == "llm_security"), None)
    assert f is not None and f.value == "mocksecret"
    assert f.kind == KIND_CREDENTIAL and f.suggested_action == "store"  # 默认动作按类别生效


async def test_security_input_is_masked_before_sending(settings):
    text = "数据库 password=Sup3rSecret! 再次出现 Sup3rSecret! 说明"
    provider = FakeProvider('{"findings": []}')
    await ScanEngine(default_policy(), security_provider=provider).scan_async(text)
    sent = json.dumps(provider.calls, ensure_ascii=False)
    assert SECRET not in sent  # 已知秘密原文绝不发送
    assert "###" in sent  # 等长掩码存在


async def test_security_layer_only_adds_or_tightens(settings):
    text = "password=Sup3rSecret! 说明"
    local = ScanEngine(default_policy()).scan(text)
    assert local and local[0].kind == KIND_CREDENTIAL
    # 模型返回低类别重叠 finding：合并只取最高类别，本地结果不被降级/删除
    provider = FakeProvider(json.dumps({"findings": [{"span": [0, 10], "kind": "unknown_suspect",
                                                       "confidence": 0.2}]}))
    merged = await ScanEngine(default_policy(), security_provider=provider).scan_async(text)
    assert all(f.kind == KIND_CREDENTIAL for f in merged)
    assert any(f.value == SECRET for f in merged)


async def test_security_failure_falls_back_to_local(settings):
    text = "password=Sup3rSecret!"
    local = ScanEngine(default_policy()).scan(text)
    merged = await ScanEngine(default_policy(), security_provider=BrokenSecurityProvider()).scan_async(text)
    assert [f.rule for f in merged] == [f.rule for f in local]
    assert any(e["kind"] == "security_model_fallback" for e in db.list_security())


async def test_security_invalid_json_falls_back(settings):
    text = "password=Sup3rSecret!"
    merged = await ScanEngine(default_policy(), security_provider=FakeProvider("不是 JSON")).scan_async(text)
    assert any(f.value == SECRET for f in merged)
    assert any(e["kind"] == "security_model_fallback" for e in db.list_security())


async def test_security_bad_output_filtered(settings):
    text = "普通内容说明AABB"
    resp = json.dumps({"findings": [
        {"span": [0, 999], "kind": "credential"},          # 越界 → 丢弃
        {"span": "x", "kind": "credential"},               # 非法类型 → 丢弃
        {"span": [0, 3], "kind": "credential", "confidence": 0.4},   # 合法
        {"span": [6, 8], "kind": "password", "confidence": 0.9},     # 非法 kind → unknown_suspect
    ]})
    findings = await ScanEngine(default_policy(), security_provider=FakeProvider(resp)).scan_async(text)
    kinds = {f.kind for f in findings}
    assert kinds == {KIND_CREDENTIAL, KIND_UNKNOWN}
    assert all(f.rule == "llm_security" for f in findings)


# ---- knowledge 必配闸门 ----

async def test_receiver_blocks_without_knowledge_model(settings):
    creds = FakeCredentialStore()
    with pytest.raises(ValueError) as ei:
        await receiver.ingest(settings, creds, text="普通内容")
    assert "知识库模型" in str(ei.value)
    assert list(settings.inbox_dir.glob("*")) == []
    assert db.list_tasks() == []


async def test_confirm_blocked_without_knowledge_model(settings):
    """先提交、再删除知识模型、最后确认：确认必须在创建任务前被拒绝，待确认记录保留。"""
    from app.security import submissions
    from app.security.policy import PolicyStore

    creds = FakeCredentialStore()
    r = await receiver.ingest(
        settings, creds, text="password=Sup3rSecret!",
        knowledge_provider_getter=lambda: FakeProvider("{}"),
    )
    view = submissions.view(settings, db.get_submission(r["submission_id"]))
    fid = view["findings"][0]["id"]
    with pytest.raises(submissions.SubmissionError) as ei:
        # 不注入 getter → 默认查库 → 无知识模型 → 拒绝
        await submissions.confirm(settings, creds, PolicyStore(settings.policy_file),
                                  r["submission_id"], {fid: "store"})
    assert "知识库模型" in str(ei.value)
    assert db.get_submission(r["submission_id"])["status"] == "waiting"  # 记录保留
    assert db.list_tasks() == []
    assert creds.created == []
    # 恢复知识库模型后重试成功
    result = await submissions.confirm(
        settings, creds, PolicyStore(settings.policy_file), r["submission_id"], {fid: "store"},
        knowledge_provider_getter=lambda: FakeProvider("{}"),
    )
    assert "task_id" in result and db.list_tasks() != []


# ---- API 层 ----

def _client(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: provider)
    return TestClient(main.app)


def test_api_blocks_ingest_and_query_without_knowledge_model(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, None) as client:
        h = client.get("/api/health").json()
        assert h["knowledge_model"] is False
        r = client.post("/api/ingest", data={"text": "普通内容"})
        assert r.status_code == 400 and "知识库模型" in r.json()["detail"]
        q = client.post("/api/query", json={"question": "测试"})
        assert q.status_code == 400 and "知识库模型" in q.json()["detail"]


def test_api_security_endpoint_policy(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, FakeProvider("OK")) as client:
        r = client.post("/api/settings/models", json={
            "name": "sec", "provider_type": "custom", "base_url": "https://8.8.8.8/v1",
            "model": "m", "role": "security", "is_active": True,
        })
        assert r.status_code == 400 and "localhost/内网" in r.json()["detail"]
        assert db.list_model_configs() == []  # 未写入
        ok = client.post("/api/settings/models", json={
            "name": "sec", "provider_type": "custom", "base_url": "http://127.0.0.1:9001/v1",
            "model": "m", "role": "security", "is_active": True,
        })
        assert ok.status_code == 200
        rows = client.get("/api/settings/models").json()
        assert rows[0]["role"] == "security"


def test_api_knowledge_single_active_per_role(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, FakeProvider("OK")) as client:
        k1 = client.post("/api/settings/models", json={
            "name": "k1", "provider_type": "custom", "base_url": "http://127.0.0.1:9001/v1",
            "model": "m1", "role": "knowledge", "is_active": True}).json()
        k2 = client.post("/api/settings/models", json={
            "name": "k2", "provider_type": "custom", "base_url": "http://127.0.0.1:9001/v1",
            "model": "m2", "role": "knowledge", "is_active": True}).json()
        rows = client.get("/api/settings/models").json()
        active = [r for r in rows if r["role"] == "knowledge" and r["is_active"]]
        assert [r["id"] for r in active] == [k2["id"]]  # 同角色只保留最后激活的一个
        # 非法角色被拒绝
        bad = client.post("/api/settings/models", json={
            "name": "bad", "provider_type": "custom", "role": "other"})
        assert bad.status_code == 400
        # 激活接口按角色切换
        client.post(f"/api/settings/models/{k1['id']}/activate")
        rows = client.get("/api/settings/models").json()
        active = [r for r in rows if r["role"] == "knowledge" and r["is_active"]]
        assert [r["id"] for r in active] == [k1["id"]]


def test_api_confirm_blocked_without_knowledge_model(tmp_path, monkeypatch):
    """复现路径：提交 → 删除知识模型 → 确认 → 400，待确认记录保留；恢复后重试成功。"""
    holder = {"p": FakeProvider("OK")}
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: holder["p"])
    with TestClient(main.app) as client:
        ing = client.post("/api/ingest", data={"text": "password=Sup3rSecret!"})
        j = ing.json()
        assert j["pending_confirmation"] is True
        sid = j["submission_id"]
        fid = j["findings"][0]["id"]
        holder["p"] = None  # 模拟删除知识库模型
        conf = client.post(f"/api/pending/submissions/{sid}/confirm",
                           json={"decisions": {fid: "store"}})
        assert conf.status_code == 400 and "知识库模型" in conf.json()["detail"]
        assert db.get_submission(sid)["status"] == "waiting"  # 待确认记录保留
        assert db.list_tasks() == []
        # 恢复知识库模型后重试成功
        holder["p"] = FakeProvider("OK")
        conf2 = client.post(f"/api/pending/submissions/{sid}/confirm",
                            json={"decisions": {fid: "store"}})
        assert conf2.status_code == 200 and "task_id" in conf2.json()
        assert db.list_tasks() != []
