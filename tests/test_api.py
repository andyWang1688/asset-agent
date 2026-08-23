import json

from fastapi.testclient import TestClient

import app.api as api_module
import app.main as main
from tests.fakes import FakeCredentialStore, FakeProvider

PLAN = json.dumps(
    {
        "source_summary": {"title": "s", "path": "sources/s.md", "content": "# s\n内容"},
        "pages": [{"action": "create", "path": "projects/p.md", "title": "p", "content": "# p\n订单服务与缓存介绍"}],
        "conflicts": [],
    },
    ensure_ascii=False,
)


def test_api_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setenv("VAULTWARDEN_URL", "http://127.0.0.1:8081")
    creds = FakeCredentialStore()
    provider = FakeProvider(PLAN)
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: creds)
    monkeypatch.setattr(main, "get_active_provider", lambda settings: provider)
    monkeypatch.setattr(api_module.llm, "build_provider", lambda settings, row, role=None: FakeProvider("OK"))

    with TestClient(main.app) as client:
        # health
        h = client.get("/api/health").json()
        assert h["status"] == "ok"
        assert h["knowledge_model"] is True

        # 内置规则逐条启停：立即生效且持久化到策略文件
        rules = client.get("/api/settings/policy/builtin-rules").json()["rules"]
        assert next(r for r in rules if r["name"] == "email")["enabled"] is True
        toggled = client.post(
            "/api/settings/policy/builtin-rules/email", json={"enabled": False}
        ).json()
        assert toggled["rule"] == {"name": "email", "kind": "pii", "enabled": False}
        policy = client.get("/api/settings/policy").json()
        assert "email" in policy["policy"]["detection"]["builtin_rules"]["disabled"]

        # 自定义规则表单 API：新增后立即生效，可逐条停用
        created_rule = client.post(
            "/api/settings/policy/custom-rules",
            json={"name": "employee_id", "pattern": r"EMP-\d{6}", "kind": "pii"},
        ).json()["rule"]
        assert created_rule["enabled"] is True
        assert "pattern" not in created_rule
        custom = client.get("/api/settings/policy/custom-rules").json()
        assert custom["rules"][0]["name"] == "employee_id"
        assert custom["validators"] == ["id_card", "luhn"]
        disabled = client.post(
            "/api/settings/policy/custom-rules/employee_id", json={"enabled": False}
        ).json()["rule"]
        assert disabled["enabled"] is False
        invalid = client.post(
            "/api/settings/policy/custom-rules",
            json={"name": "bad", "pattern": "a" * 301, "kind": "pii"},
        )
        assert invalid.status_code == 400 and "长度" in invalid.json()["detail"]

        # 模型配置页面化：保存 + 列表不泄露 key + 测试
        saved = client.post(
            "/api/settings/models",
            json={"name": "mock", "provider_type": "custom", "base_url": "http://x/v1",
                  "api_key": "sk-secret-key-123", "model": "m1", "is_active": True,
                  "role": "knowledge"},
        ).json()
        models = client.get("/api/settings/models").json()
        assert models[0]["api_key_set"] is True
        assert models[0]["role"] == "knowledge"
        assert "sk-secret-key-123" not in json.dumps(models)
        test = client.post(f"/api/settings/models/{saved['id']}/test").json()
        assert test["ok"] is True

        # 输入（含秘密）：先进入确认闸门，未经确认不写 Vaultwarden、不建任务
        r = client.post("/api/ingest", data={"text": "password=Sup3rSecret! 订单服务"}).json()
        assert r["pending_confirmation"] is True
        sid = r["submission_id"]
        assert r["summary"]["credential"] == 1
        assert "Sup3rSecret!" not in json.dumps(r)
        assert creds.created == []

        view = client.get(f"/api/pending/submissions/{sid}").json()
        fid = view["findings"][0]["id"]
        assert "Sup3rSecret!" not in json.dumps(view)

        confirmed = client.post(
            f"/api/pending/submissions/{sid}/confirm", json={"decisions": {fid: "store"}}
        ).json()
        assert confirmed["secrets_count"] == 1 and confirmed["secrets"][0]["saved"] is True
        assert creds.created[0].value == "Sup3rSecret!"

        # 后台 worker 在 TestClient 的 event loop 中运行，轮询任务状态
        import time
        for _ in range(20):
            tasks = client.get("/api/tasks").json()
            if tasks[0]["status"] in ("done", "failed"):
                break
            time.sleep(0.3)
        assert tasks[0]["status"] == "done"

        # Wiki
        pages = client.get("/api/wiki/pages").json()
        assert any(p["path"] == "projects/p.md" for p in pages)
        content = client.get("/api/wiki/page", params={"path": "projects/p.md"}).json()
        assert "订单服务" in content["content"]

        # 问答（fake provider 换用问答响应）
        provider.response = "根据 [[projects/p.md|p]]：订单服务说明。"
        q = client.post("/api/query", json={"question": "订单服务是什么"}).json()
        assert "projects/p.md" in q["answer"]
        history = client.get("/api/chat/history").json()
        assert history[0]["answer"] == q["answer"]

        # 凭证元数据
        secrets = client.get("/api/secrets").json()
        assert secrets[0]["name"] == "password"
        assert "Sup3rSecret!" not in json.dumps(secrets)

        # 安全事件
        events = client.get("/api/security/events").json()
        assert isinstance(events, list)


def test_query_engine_is_replaceable(tmp_path, monkeypatch):
    class FakeQueryEngine:
        def __init__(self):
            self.calls = []

        async def answer(self, provider, question):
            self.calls.append((provider, question))
            return {"answer": "替身回答", "citations": ["fake.md"]}

    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    provider = FakeProvider("不应调用")
    monkeypatch.setattr(main, "get_active_provider", lambda settings: provider)

    engine = FakeQueryEngine()
    with TestClient(main.app) as client:
        main.app.state.ctx.get_query_engine = lambda: engine
        response = client.post(
            "/api/query", json={"question": "测试问题", "session_id": "session-1"}
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "替身回答", "citations": ["fake.md"]}
    assert engine.calls[0][1] == "测试问题"
    assert provider.calls == []


def test_replacement_engine_stays_behind_security_gates(tmp_path, monkeypatch):
    class FakeQueryEngine:
        def __init__(self):
            self.calls = []

        async def answer(self, provider, question):
            self.calls.append(question)
            return {
                "answer": "密码是 sk-proj-abcdEFGH12345678901234567890",
                "citations": [],
            }

    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ws" / ".asset-assistant"))
    monkeypatch.setattr(main, "VaultwardenAdapter", lambda settings: FakeCredentialStore())
    monkeypatch.setattr(main, "get_active_provider", lambda settings: FakeProvider("不应调用"))

    engine = FakeQueryEngine()
    with TestClient(main.app) as client:
        main.app.state.ctx.get_query_engine = lambda: engine
        blocked = client.post("/api/query", json={"question": "password=Sup3rSecret! 是什么"})
        sanitized = client.post("/api/query", json={"question": "Demo 联系 user@example.com"})

    assert blocked.status_code == 400
    assert len(engine.calls) == 1
    assert "user@example.com" not in engine.calls[0]
    assert "sk-proj" not in sanitized.json()["answer"]
