"""接收与任务编排：内存扫描 → 闸门（有 Finding 时进入待确认加密队列）→ 落盘 → 编译任务。

安全不变量：秘密原文不落盘、不进日志、不进 LLM；任何持久化动作（Raw/SQLite/
Vaultwarden/云端模型）都发生在确认之后（或策略显式关闭闸门时）。
"""
from .. import crypto, db
from ..config import Settings
from ..credentials.base import CredentialStore
from ..ingest import finalize as finalize_mod
from ..security import submissions
from ..security.detectors import ScanEngine
from ..security.policy import PolicyStore
from .parsers import parse_upload


async def ingest(
    settings: Settings,
    creds: CredentialStore,
    *,
    text: str | None = None,
    filename: str | None = None,
    data: bytes | None = None,
    policy_store: PolicyStore | None = None,
    knowledge_provider_getter=None,
    security_provider=None,
) -> dict:
    # knowledge 模型必配闸门（fail-closed）：未配置/激活时禁止提交编译任务，任何介质都不写入。
    # security 模型可选：未配置时仅本地检测管线生效。
    if knowledge_provider_getter is None:
        from ..llm.provider import get_active_provider

        knowledge_provider_getter = lambda: get_active_provider(settings)
    if knowledge_provider_getter() is None:
        raise ValueError(
            "未配置知识库模型：Wiki 编译与问答需要先配置并激活一个知识库模型"
            "（设置 → 模型配置），本次提交已被阻止（未保存、未发送）"
        )
    if text is not None:
        kind, text = "text", text.strip()
        original_name = "pasted.txt"
    else:
        kind, text = parse_upload(filename or "", data or b"", settings.max_upload_mb)
        text = text.strip()
        original_name = filename or "upload.txt"
    if not text:
        raise ValueError("内容为空")

    sha = crypto.sha256_hex(text)
    # 幂等：已处理（confirmed=1）内容直接返回既有来源，不重复创建凭证/Wiki 页面；
    # confirmed=0 占位由 finalize 的 claim 阶段处理（崩溃遗留复用或冲突返回）
    existing = db.get_source_by_sha256(sha)
    if existing and existing["confirmed"]:
        return {"source_id": existing["id"], "duplicate": True, "message": "内容已存在，未重复处理", "secrets": []}

    store = policy_store or PolicyStore(settings.policy_file)
    policy = store.load()

    def _warn(msg: str) -> None:
        db.log_security("detector_warning", msg)

    engine = ScanEngine(policy, on_warning=_warn, security_provider=security_provider)
    # 输入先在内存扫描：任何介质写入之前；基础检测器失败必须阻断。
    # security 增强层失败仅回退本地检测结果（可选层）。
    try:
        findings = await engine.scan_async(text)
    except Exception as e:  # 基础检测器失败：阻断（绝不带着未扫描的明文继续）
        db.log_security("detector_failed", f"检测器失败已阻断提交: {type(e).__name__}")
        raise ValueError("检测器失败，本次提交已阻断（未保存、未发送）") from e

    gate = policy.get("gate", {}).get("confirm_before_llm", "on_findings")
    if gate == "always" or (gate == "on_findings" and findings):
        existing_sub = db.submission_by_sha256(sha)
        if existing_sub:
            return {"pending_confirmation": True,
                    **submissions.view(settings, existing_sub)}
        if db.submission_count_waiting() >= settings.pending_submission_limit:
            raise ValueError("待确认队列已满，请先处理或取消已有提交")
        sid = submissions.create_submission(settings, text, findings, sha, kind, original_name, policy=policy)
        row = db.get_submission(sid)
        return {"pending_confirmation": True, **submissions.view(settings, row)}

    # 闸门关闭（gate=never 且无 Finding，或显式 never）：按默认动作直接处理
    try:
        result = await finalize_mod.finalize(
            settings, creds, text=text, sha=sha, kind=kind, original_name=original_name,
            findings=findings, decisions=None, engine=engine, policy=policy,
        )
    except finalize_mod.DuplicateSourceError as dup:
        return {"source_id": dup.source_id, "duplicate": True, "message": "内容已存在，未重复处理", "secrets": []}
    return result
