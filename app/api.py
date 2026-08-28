"""HTTP API：输入、确认闸门、问答、Wiki、任务、凭证元数据、模型与安全策略配置、安全事件。"""
import json
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict

from . import crypto, db
from .credentials.base import CredentialError
from .ingest import receiver
from .llm import provider as llm
from .query import model_download, rebuild, retrieval, retrieval_config, service as query_service
from .security import submissions
from .security.policy import PolicyStore
from .security.rules import VALIDATORS
from .wiki import compiler

router = APIRouter()


class ModelBody(BaseModel):
    id: int | None = None
    name: str
    provider_type: str = "custom"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    is_active: bool = True
    role: str = "knowledge"


class ConfirmBody(BaseModel):
    decisions: dict[str, str] = {}
    edited_text: str | None = None


class PolicyBody(BaseModel):
    yaml: str


class SecurityKeywordsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    items: list[str] | None = None


class SecurityEntropyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    sensitivity: Literal["sensitive", "balanced", "conservative"] | None = None


class SecuritySettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["default", "confirm"] | None = None
    keywords: SecurityKeywordsBody | None = None
    entropy: SecurityEntropyBody | None = None


class BuiltinRuleBody(BaseModel):
    enabled: bool


class BuiltinOverrideBody(BaseModel):
    pattern: str | None = None
    kind: str | None = None


class CustomRuleBody(BaseModel):
    name: str
    pattern: str
    kind: str
    validator: str | None = None


class CustomRuleToggleBody(BaseModel):
    enabled: bool


class RetrievalConfigBody(BaseModel):
    provider: str = retrieval_config.PROVIDER_ST
    model: str
    reranker_enabled: bool = True
    reranker_model: str = ""
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_ack: bool = False


class ModelDownloadBody(BaseModel):
    provider: str = retrieval_config.PROVIDER_ST
    model: str


def _ctx(request: Request):
    return request.app.state.ctx


def _policy_store(request: Request) -> PolicyStore:
    ctx = _ctx(request)
    return getattr(ctx, "policy_store", None) or PolicyStore(ctx.settings.policy_file)


@router.get("/api/health")
def health(request: Request):
    ctx = _ctx(request)
    return {
        "status": "ok",
        "vaultwarden_cli": ctx.creds.available(),
        "vaultwarden_configured": ctx.creds.configured(),
        "model": ctx.get_provider() is not None,
        "knowledge_model": ctx.get_provider() is not None,
        "security_model": ctx.get_security_provider() is not None,
        "pending_secrets": db.list_pending("pending").__len__(),
    }


@router.get("/api/settings/status")
def settings_status(request: Request):
    """设置中心五模块的真实运行状态摘要。"""
    ctx = _ctx(request)
    rules = _policy_store(request).rules_detail()
    semantic_enabled = getattr(ctx, "retrieval_semantic_enabled", None)
    return {
        "knowledge_model": ctx.get_provider() is not None,
        "retrieval_degraded": semantic_enabled is False,
        "retrieval_checked": semantic_enabled is not None,
        "rules_enabled": sum(1 for rule in rules if rule["enabled"]),
        "rules_total": len(rules),
        "policy_valid": True,
        "pending_security_events": len(db.list_pending("pending")),
    }


@router.post("/api/ingest")
async def ingest(
    request: Request,
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    ctx = _ctx(request)
    # knowledge 模型必配闸门（fail-closed）：未配置/激活时禁止提交编译任务，UI 明确提示
    if ctx.get_provider() is None:
        raise HTTPException(400, "未配置知识库模型：Wiki 编译任务禁止提交。请先在「设置」页配置并激活一个知识库模型。")
    try:
        if file is not None:
            data = await file.read()
            result = await receiver.ingest(
                ctx.settings, ctx.creds, filename=file.filename, data=data,
                policy_store=_policy_store(request),
                knowledge_provider_getter=lambda: ctx.get_provider(),
                security_provider=ctx.get_security_provider(),
            )
        elif text:
            result = await receiver.ingest(
                ctx.settings, ctx.creds, text=text, policy_store=_policy_store(request),
                knowledge_provider_getter=lambda: ctx.get_provider(),
                security_provider=ctx.get_security_provider(),
            )
        else:
            raise HTTPException(400, "请粘贴文本或选择文件")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return result


# ---- 确认闸门：待确认提交 ----

def _json_loads_default(s: str | None):
    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        return {}


@router.get("/api/pending/submissions")
def pending_submissions(request: Request):
    rows = db.list_submissions()
    return [
        {
            "id": r["id"],
            "status": r["status"],
            "sha256": r["sha256"][:16],
            "original_name": r["original_name"],
            "summary": _json_loads_default(r["findings_summary"]),
            "created_at": r["created_at"],
            "resolved_at": r["resolved_at"],
        }
        for r in rows
    ]


@router.get("/api/pending/submissions/{submission_id}")
def pending_submission_view(request: Request, submission_id: int):
    ctx = _ctx(request)
    row = db.get_submission(submission_id)
    if not row:
        raise HTTPException(404, "提交不存在")
    try:
        return submissions.view(ctx.settings, row)
    except submissions.SubmissionError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/pending/submissions/{submission_id}/confirm")
async def pending_submission_confirm(request: Request, submission_id: int, body: ConfirmBody):
    ctx = _ctx(request)
    try:
        return await submissions.confirm(
            ctx.settings, ctx.creds, _policy_store(request), submission_id, body.decisions,
            edited_text=body.edited_text, security_provider=ctx.get_security_provider(),
            knowledge_provider_getter=lambda: ctx.get_provider(),
        )
    except submissions.SubmissionError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/pending/submissions/{submission_id}/cancel")
def pending_submission_cancel(request: Request, submission_id: int):
    ctx = _ctx(request)
    try:
        submissions.cancel(ctx.settings, submission_id)
    except submissions.SubmissionError as e:
        raise HTTPException(400, str(e)) from e
    return {"cancelled": True}


# ---- 安全策略（设置服务读写，Wiki LLM 只读） ----

@router.get("/api/settings/security")
def get_security_settings(request: Request):
    return _policy_store(request).security_settings()


@router.patch("/api/settings/security")
def update_security_settings(request: Request, body: SecuritySettingsBody):
    try:
        settings = _policy_store(request).update_security_settings(
            body.model_dump(exclude_none=True, exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", "安全策略页面配置已更新并生效")
    return {"ok": True, **settings}

@router.get("/api/settings/policy")
def get_policy(request: Request):
    store = _policy_store(request)
    return {"policy": store.load(), "yaml": store.dump()}


@router.post("/api/settings/policy")
def save_policy(request: Request, body: PolicyBody):
    store = _policy_store(request)
    policy, errors = store.save(body.yaml)
    if errors:
        raise HTTPException(400, "；".join(errors))
    db.log_security("policy_updated", "安全策略已更新并生效")
    return {"ok": True, "policy": policy}


@router.get("/api/settings/policy/builtin-rules")
def get_builtin_rules(request: Request):
    return {"rules": _policy_store(request).builtin_rules()}


@router.post("/api/settings/policy/builtin-rules/{rule_name}")
def set_builtin_rule(request: Request, rule_name: str, body: BuiltinRuleBody):
    try:
        rule = _policy_store(request).set_builtin_rule(rule_name, body.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"内置规则 {rule_name} 已{'启用' if body.enabled else '停用'}")
    return {"ok": True, "rule": rule}


@router.get("/api/settings/policy/rules")
def get_policy_rules(request: Request):
    """统一规则列表：内置（含覆盖）+ 自定义，含名称/类别/描述/示例/正则/来源/启停。"""
    return {"rules": _policy_store(request).rules_detail(), "validators": sorted(VALIDATORS)}


@router.put("/api/settings/policy/builtin-rules/{rule_name}/override")
def set_builtin_override(request: Request, rule_name: str, body: BuiltinOverrideBody):
    try:
        rule = _policy_store(request).set_builtin_override(rule_name, body.pattern, body.kind)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"内置规则 {rule_name} 已覆盖（正则/类别）")
    return {"ok": True, "rule": rule}


@router.delete("/api/settings/policy/builtin-rules/{rule_name}/override")
def restore_builtin_rule(request: Request, rule_name: str):
    try:
        rule = _policy_store(request).restore_builtin_rule(rule_name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"内置规则 {rule_name} 已恢复默认")
    return {"ok": True, "rule": rule}


@router.get("/api/settings/policy/custom-rules")
def get_custom_rules(request: Request):
    return {"rules": _policy_store(request).custom_rules(), "validators": sorted(VALIDATORS)}


@router.post("/api/settings/policy/custom-rules")
def add_custom_rule(request: Request, body: CustomRuleBody):
    try:
        rule = _policy_store(request).add_custom_rule(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"自定义规则 {rule['name']} 已新增并启用")
    return {"ok": True, "rule": rule}


@router.post("/api/settings/policy/custom-rules/{rule_name}")
def set_custom_rule(request: Request, rule_name: str, body: CustomRuleToggleBody):
    try:
        rule = _policy_store(request).set_custom_rule(rule_name, body.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"自定义规则 {rule_name} 已{'启用' if body.enabled else '停用'}")
    return {"ok": True, "rule": rule}


@router.delete("/api/settings/policy/custom-rules/{rule_name}")
def delete_custom_rule(request: Request, rule_name: str):
    try:
        _policy_store(request).delete_custom_rule(rule_name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    db.log_security("policy_updated", f"自定义规则 {rule_name} 已删除")
    return {"ok": True}


@router.get("/api/sources")
def sources(request: Request, limit: int = 50):
    rows = db.list_sources(limit)
    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "original_name": r["original_name"],
            "sha256": r["sha256"][:16],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.get("/api/sources/{source_id}/raw")
def source_raw(request: Request, source_id: int):
    row = db.get_source(source_id)
    if not row:
        raise HTTPException(404, "来源不存在")
    p = Path(row["path"])
    if not p.exists():
        raise HTTPException(404, "原始文件不存在")
    return {"path": row["path"], "content": p.read_text(encoding="utf-8")}


@router.get("/api/tasks")
def tasks(request: Request, limit: int = 100):
    rows = db.list_tasks(limit=limit)
    return [
        {
            "id": r["id"],
            "source_id": r["source_id"],
            "status": r["status"],
            "error": r["error"],
            "retries": r["retries"],
            "original_name": r["original_name"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


@router.post("/api/tasks/{task_id}/retry")
def retry_task(request: Request, task_id: int):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t["status"] not in ("failed", "credential_pending"):
        raise HTTPException(400, f"状态 {t['status']} 不可重试")
    db.update_task_status(task_id, "pending")
    return {"id": task_id, "status": "pending"}


class QueryBody(BaseModel):
    question: str
    session_id: str | None = None


@router.post("/api/query")
async def query(request: Request, body: QueryBody):
    ctx = _ctx(request)
    provider = ctx.get_provider()
    if provider is None:
        raise HTTPException(400, "未配置知识库模型：问答已禁用。请先在「设置」页配置并激活一个知识库模型。")
    try:
        result = await query_service.answer(
            ctx.settings, provider, body.question,
            security_provider=ctx.get_security_provider(), session_id=body.session_id,
            engine=ctx.get_query_engine(),
        )
        ctx.retrieval_semantic_enabled = result["semantic_retrieval_enabled"]
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except llm.LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/api/chat/history")
def chat_history(limit: int = 50):
    import json

    sessions = {s["session_id"]: s for s in db.list_sessions()}
    rows = db.list_chat(limit)
    out = []
    for r in rows:
        key = r["session_id"] or f"legacy-{r['id']}"
        s = sessions.get(key)
        out.append(
            {
                "id": r["id"],
                "question": r["question"],
                "answer": r["answer"],
                "citations": json.loads(r["citations"] or "[]"),
                "session_id": r["session_id"],
                "title": s["title"] if s else None,
                "pinned": bool(s["pinned"]) if s else False,
                "created_at": r["created_at"],
            }
        )
    return out


class SessionTitleBody(BaseModel):
    session_id: str
    title: str


class SessionPinBody(BaseModel):
    session_id: str
    pinned: bool


class SessionAdoptBody(BaseModel):
    session_id: str
    entry_ids: list[int]


@router.post("/api/chat/session/adopt")
def chat_session_adopt(body: SessionAdoptBody):
    db.adopt_session(body.session_id, body.entry_ids)
    return {"ok": True}


@router.post("/api/chat/session/title")
def chat_session_title(body: SessionTitleBody):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    db.set_session_title(body.session_id, title[:60])
    return {"ok": True}


@router.post("/api/chat/session/pin")
def chat_session_pin(body: SessionPinBody):
    db.set_session_pinned(body.session_id, body.pinned)
    return {"ok": True}


@router.delete("/api/chat/session")
def chat_session_delete(session_id: str):
    db.delete_session(session_id)
    return {"ok": True}


@router.get("/api/wiki/pages")
def wiki_pages(request: Request):
    ctx = _ctx(request)
    return compiler._list_pages(ctx.settings)


@router.get("/api/wiki/page")
def wiki_page(request: Request, path: str):
    ctx = _ctx(request)
    try:
        p = compiler.safe_wiki_path(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    target = (ctx.settings.wiki_dir / p).resolve()
    if not target.is_relative_to(ctx.settings.wiki_dir.resolve()):
        raise HTTPException(400, "非法路径")
    if not target.exists():
        raise HTTPException(404, "页面不存在")
    return {"path": path, "content": target.read_text(encoding="utf-8")}


@router.post("/api/wiki/rebuild")
def wiki_rebuild(request: Request):
    ctx = _ctx(request)
    compiler.rebuild_index(ctx.settings)
    return {"ok": True}


@router.get("/api/secrets")
async def secrets(request: Request):
    ctx = _ctx(request)
    try:
        items = await ctx.creds.list_items()
    except CredentialError as e:
        raise HTTPException(503, f"凭证库不可用: {e}") from e
    return [{"name": m.name, "item_id": m.item_id, "note": m.note, "updated_at": m.updated_at} for m in items]


@router.get("/api/pending")
def pending_list():
    rows = db.list_pending()
    return [
        {"id": r["id"], "source_id": r["source_id"], "name": r["name"],
         "status": r["status"], "retries": r["retries"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.post("/api/pending/cleanup")
def pending_cleanup():
    n = 0
    for r in db.list_pending():
        if r["status"] != "pending":
            db.delete_pending(r["id"])
            n += 1
    return {"deleted": n}


@router.get("/api/settings/presets")
def presets():
    return [{"type": k, "name": v[0], "base_url": v[1], "model": v[2]} for k, v in llm.PRESETS.items()]


@router.get("/api/settings/models")
def models(request: Request):
    ctx = _ctx(request)
    rows = db.list_model_configs()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "provider_type": r["provider_type"],
            "base_url": r["base_url"],
            "api_key_set": bool(r["api_key_enc"]),
            "model": r["model"],
            "is_active": bool(r["is_active"]),
            "role": r["role"],
        }
        for r in rows
    ]


@router.post("/api/settings/models")
def save_model(request: Request, body: ModelBody):
    ctx = _ctx(request)
    if body.provider_type not in llm.PRESETS:
        raise HTTPException(400, "未知 provider_type")
    if body.role not in llm.MODEL_ROLES:
        raise HTTPException(400, f"role 必须是 {llm.MODEL_ROLES} 之一")
    old = None
    if body.id:
        old = db.get_model_config(body.id)
        if not old:
            raise HTTPException(404, "配置不存在")
    # 生效的 API 地址（填写优先，其次既有配置，最后预设）
    effective_base = body.base_url or (old["base_url"] if old else "") or llm.PRESETS[body.provider_type][1]
    if body.role == llm.ROLE_SECURITY:
        err = llm.validate_security_endpoint(effective_base)
        if err:
            raise HTTPException(400, err)
    api_key_enc = ""
    if old:
        api_key_enc = old["api_key_enc"]
    if body.api_key:
        api_key_enc = crypto.seal(ctx.settings.local_key(), body.api_key.encode())
    try:
        cfg_id = db.upsert_model_config(
            body.id, body.name, body.provider_type, body.base_url, api_key_enc, body.model,
            body.is_active, body.role,
        )  # is_active 的停用+激活在同一事务内原子完成（部分唯一索引兜底）
    except sqlite3.IntegrityError:
        raise HTTPException(400, "同角色激活配置切换冲突，请重试") from None
    return {"id": cfg_id}


@router.post("/api/settings/models/{cfg_id}/activate")
def activate_model(cfg_id: int):
    if not db.get_model_config(cfg_id):
        raise HTTPException(404, "配置不存在")
    db.activate_model_config(cfg_id)
    return {"ok": True}


@router.post("/api/settings/models/{cfg_id}/test")
async def test_model(request: Request, cfg_id: int):
    ctx = _ctx(request)
    row = db.get_model_config(cfg_id)
    if not row:
        raise HTTPException(404, "配置不存在")
    try:
        p = llm.build_provider(ctx.settings, dict(row), role=row["role"])
        # 推理模型会把预算花在思考上：过小（如 16）会耗尽 token 导致 content 为空
        out = await p.complete("你是连通性测试助手。", "【连通性测试】请只回复 OK", max_tokens=256)
        return {"ok": True, "reply": out[:100]}
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}


@router.delete("/api/settings/models/{cfg_id}")
def delete_model(cfg_id: int):
    if not db.get_model_config(cfg_id):
        raise HTTPException(404, "配置不存在")
    db.delete_model_config(cfg_id)
    return {"ok": True}


# ---- 检索配置（问答子系统）：单实例单配置，页面写入优先于环境变量 ----

def _retrieval_view(request: Request) -> dict:
    """返回当前生效配置的只读视图：API Key 只给 set 布尔值，不回显。"""
    from .query.hybrid import DEFAULT_RERANK_MODEL

    ctx = _ctx(request)
    page = retrieval_config.page_config()
    if page is not None:
        return {
            "configured": True,
            "source": "page",
            "provider": page["provider"],
            "model": page["model"],
            "reranker_enabled": page["reranker_enabled"],
            "reranker_model": page["reranker_model"],
            "cloud_base_url": page["cloud_base_url"],
            "cloud_api_key_set": bool(page["cloud_api_key_enc"]),
            "recommended": {
                "embeddings": retrieval_config.RECOMMENDED_EMBEDDINGS,
                "rerankers": retrieval_config.RECOMMENDED_RERANKERS,
            },
        }
    env = retrieval_config.env_signature(ctx.settings)
    return {
        "configured": False,
        "source": "env",
        "provider": env["provider"],
        "model": env["model"],
        "reranker_enabled": str(getattr(ctx.settings, "reranker", "local")).strip().lower() not in {"off", "none", "false", ""},
        "reranker_model": str(getattr(ctx.settings, "reranker_model", "") or DEFAULT_RERANK_MODEL),
        "cloud_base_url": env.get("cloud_base_url", ""),
        "cloud_api_key_set": bool(env.get("api_key")),
        "recommended": {
            "embeddings": retrieval_config.RECOMMENDED_EMBEDDINGS,
            "rerankers": retrieval_config.RECOMMENDED_RERANKERS,
        },
    }

@router.get("/api/settings/retrieval")
def get_retrieval(request: Request):
    return _retrieval_view(request)


@router.post("/api/settings/retrieval")
def save_retrieval(request: Request, body: RetrievalConfigBody):
    ctx = _ctx(request)
    if body.provider not in retrieval_config.PROVIDERS:
        raise HTTPException(400, f"后端路线必须是 {retrieval_config.PROVIDERS} 之一")
    model = body.model.strip()
    if not model:
        raise HTTPException(400, "模型名不能为空")
    if body.provider == retrieval_config.PROVIDER_CLOUD:
        if not body.cloud_base_url.strip():
            raise HTTPException(400, "云端路线必须填写 API 地址")
        if not body.cloud_ack:
            raise HTTPException(400, "云端路线需勾选确认：知识库内容将发送到该端点")
    # API Key：仅云端路线加密存储；留空保持不变，禁止明文落库。
    api_key_enc = ""
    if body.provider == retrieval_config.PROVIDER_CLOUD:
        old = retrieval_config.page_config()
        if body.cloud_api_key:
            api_key_enc = crypto.seal(ctx.settings.local_key(), body.cloud_api_key.encode())
        elif old is not None:
            api_key_enc = old["cloud_api_key_enc"]

    old_signature = retrieval_config.embedding_signature(ctx.settings)
    db.save_retrieval_config(
        body.provider, model, 1 if body.reranker_enabled else 0, body.reranker_model.strip(),
        body.cloud_base_url.strip() if body.provider == retrieval_config.PROVIDER_CLOUD else "",
        api_key_enc,
    )
    new_signature = retrieval_config.embedding_signature(ctx.settings)
    rebuild_triggered = False
    if new_signature != old_signature and retrieval.has_index(ctx.settings):
        # 向量不兼容的配置变更：后台自动重建索引（不做手动选项）。
        # 重建先写 staging 再原子换名，期间旧索引继续服务，问答行为不变。
        rebuild.manager.start(ctx.settings, retrieval_config.page_config())
        rebuild_triggered = True
    return {"ok": True, "rebuild_triggered": rebuild_triggered, "config": _retrieval_view(request)}


@router.post("/api/settings/retrieval/test")
async def test_retrieval(request: Request, body: RetrievalConfigBody):
    """测试端点：嵌一段固定文本并返回维度；不可用时返回友好错误（不抛 HTTP 异常）。"""
    import asyncio

    from .query.embeddings import EmbeddingError

    ctx = _ctx(request)
    if body.provider not in retrieval_config.PROVIDERS:
        return {"ok": False, "error": f"后端路线必须是 {retrieval_config.PROVIDERS} 之一"}
    if not body.model.strip():
        return {"ok": False, "error": "模型名不能为空"}
    api_key = body.cloud_api_key
    if not api_key:
        page = retrieval_config.page_config()
        if page is not None and page["cloud_api_key_enc"]:
            try:
                api_key = crypto.open_sealed(ctx.settings.local_key(), page["cloud_api_key_enc"]).decode("utf-8")
            except Exception:
                api_key = ""
    try:
        embedder = retrieval_config.build_test_embedder(
            ctx.settings, provider=body.provider, model=body.model.strip(),
            base_url=body.cloud_base_url, api_key=api_key,
        )
        vector = await asyncio.wait_for(
            asyncio.to_thread(embedder.get_text_embedding, "资产检索连通性测试"),
            timeout=ctx.settings.embedding_timeout,
        )
    except EmbeddingError as e:
        return {"ok": False, "error": str(e)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "测试超时：模型加载或请求超过限制，请检查网络后重试"}
    except Exception as e:
        return {"ok": False, "error": retrieval_config.friendly_error(body.provider, e)}
    return {"ok": True, "dimension": len(vector)}


@router.delete("/api/settings/retrieval")
def reset_retrieval(request: Request):
    """清除页面配置，恢复环境变量语义（环境变量继续有效）。"""
    ctx = _ctx(request)
    old_signature = retrieval_config.embedding_signature(ctx.settings)
    db.delete_retrieval_config()
    if old_signature != retrieval_config.embedding_signature(ctx.settings) and retrieval.has_index(ctx.settings):
        # 恢复环境变量语义同样可能导致向量不兼容：与保存同一重建语义。
        rebuild.manager.start(ctx.settings, None)
    return {"ok": True}


# ---- 模型下载服务（检索配置）：HF 模型 ID → 数据目录持久卷，后台线程 + 进度查询 ----

@router.post("/api/settings/retrieval/download")
def start_model_download(request: Request, body: ModelDownloadBody):
    """启动模型下载（幂等）。仅 sentence-transformers 路线需要下载 HF 权重；
    Ollama 指引 `ollama pull`，云端无需下载。返回任务快照，不等待完成。"""
    ctx = _ctx(request)
    if body.provider == retrieval_config.PROVIDER_OLLAMA:
        raise HTTPException(400, "Ollama 路线无需走模型下载：请在 Ollama 中执行 `ollama pull <模型名>` 拉取。")
    if body.provider == retrieval_config.PROVIDER_CLOUD:
        raise HTTPException(400, "云端模型无需下载。")
    if body.provider != retrieval_config.PROVIDER_ST:
        raise HTTPException(400, f"后端路线必须是 {retrieval_config.PROVIDERS} 之一")
    model = body.model.strip()
    error = model_download.validate_model_id(model)
    if error:
        raise HTTPException(400, error)
    job, started = model_download.manager.start(model, ctx.settings.data_dir)
    return {"ok": True, "started": started, "download": job.snapshot()}


@router.get("/api/settings/retrieval/download/status")
def model_download_status(request: Request, model: str):
    """查询下载进度：状态（queued/downloading/done/failed/unknown）+ 百分比 + 字节/文件计数。"""
    ctx = _ctx(request)
    return model_download.manager.status_view(model, ctx.settings.data_dir)


@router.get("/api/settings/retrieval/rebuild/status")
def retrieval_rebuild_status():
    """查询索引重建进度：状态（idle/queued/running/done/failed）+ 页面数 + 错误。"""
    return rebuild.manager.status()


@router.get("/api/security/events")
def security_events(limit: int = 50):
    rows = db.list_security(limit)
    return [{"id": r["id"], "kind": r["kind"], "detail": r["detail"], "created_at": r["created_at"]} for r in rows]


@router.delete("/api/security/events")
def clear_security_events():
    db.clear_security()
    return {"ok": True}
