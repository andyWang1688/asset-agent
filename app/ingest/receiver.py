"""接收与任务编排：内存扫描 → 闸门（有 Finding 时进入待确认加密队列）→ 落盘 → 编译任务。

安全不变量：秘密原文不落盘、不进日志、不进 LLM；任何持久化动作（Raw/SQLite/
Vaultwarden/云端模型）都发生在确认之后（或策略显式关闭闸门时）。
"""
import json
from dataclasses import replace

from .. import crypto, db
from ..config import Settings
from ..credentials.base import CredentialStore
from ..ingest import finalize as finalize_mod
from ..security import submissions
from ..security import report as report_mod
from ..security import entries as entries_mod
from ..security.detectors import ScanEngine
from ..security.policy import PolicyStore
from .parsers import parse_upload
from .names import text_source_name


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
    session_id: str | None = None,
    instruction: str | None = None,
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
    # Session 固定模式闸门：资料提交只允许维护会话（ask 会话只读，不能写）。
    if session_id is None or db.session_mode(session_id) != db.SESSION_MAINTAIN:
        raise ValueError("仅维护会话可提交资料：请先创建一个维护模式的会话")
    review_layout = []
    if text is not None:
        kind, text = "text", text.strip()
        original_name = "pasted.txt"
        instruction = None  # 手动文字本身就是 Source，无独立整理要求
        is_file = False
    else:
        kind, text = parse_upload(filename or "", data or b"", settings.max_upload_mb, review_layout)
        text = text.strip()
        original_name = filename or "upload.txt"
        instruction = (instruction or "").strip() or None
        is_file = True
    if not text:
        raise ValueError("内容为空")

    sha = crypto.sha256_hex(text)
    # 幂等：已处理（confirmed=1）内容直接返回既有来源，不重复创建凭证/Wiki 页面；
    # 失败轮重投例外：同一内容在任务失败后重发起维护，复用来源但另起报告与任务；
    # confirmed=0 占位由 finalize 的 claim 阶段处理（崩溃遗留复用或冲突返回）
    existing = db.get_source_by_sha256(sha)
    if existing and existing["confirmed"] and not is_file and finalize_mod.retry_source_id(sha) is None:
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

    # 上传文件名也是用户输入：进入原始文件头前扫描并脱敏（避免绕过安全检测）。
    if is_file and original_name and original_name != "upload.txt":
        try:
            name_findings = await engine.scan_async(original_name)
        except Exception as e:
            db.log_security("detector_failed", f"文件名检测失败已阻断提交: {type(e).__name__}")
            raise ValueError("文件名检测失败，本次提交已阻断（未保存、未发送）") from e
        if name_findings:
            original_name, _ = finalize_mod.apply_decisions(
                original_name, name_findings, {f.id: "redact" for f in name_findings}
            )

    # 文件附带的整理要求（instruction）：走同一检测/保存决定链，带明确来源定位；
    # 绝不静默丢弃，也绝不当作文件原文。
    instruction_findings: list = []
    sources: dict = {}
    redacted_instruction = ""
    if instruction is not None:
        try:
            instruction_findings = await engine.scan_async(instruction)
        except Exception as e:
            db.log_security("detector_failed", f"整理要求检测失败已阻断提交: {type(e).__name__}")
            raise ValueError("整理要求检测失败，本次提交已阻断（未保存、未发送）") from e
        instruction_findings = [replace(f, id=f"instruction:{crypto.sha256_hex(instruction)[:16]}:{f.id}")
                                for f in instruction_findings]
        sources = {f.id: "整理要求" for f in instruction_findings}

    combined_findings = list(findings) + instruction_findings

    gate = policy.get("gate", {}).get("confirm_before_llm", "never")
    decisions_default = {f.id: f.suggested_action for f in combined_findings}
    file_entries, instr_entries = entries_mod.build_all_entries(
        findings, instruction_findings, decisions_default,
        namespace=sha, policy=policy, sources=sources,
    )
    all_entries = file_entries + instr_entries
    preview, _ = entries_mod.apply_entries(text, file_entries)
    if not is_file:
        original_name = text_source_name(preview)
    if instruction is not None:
        redacted_instruction, _ = entries_mod.apply_entries(instruction, instr_entries)
    if gate == "always":
        existing_sub = db.submission_by_sha256(submissions.submission_key(sha, instruction), session_id)
        if existing_sub:
            return {"pending_confirmation": True,
                    **submissions.view(settings, existing_sub)}
        if db.submission_count_waiting() >= settings.pending_submission_limit:
            raise ValueError("待确认队列已满，请先处理或取消已有提交")
        draft = report_mod.build_report(all_entries, original_name, preview,
                                        instruction=redacted_instruction)
        report_id = db.insert_report(
            session_id, None, "pending", "confirm", kind, original_name, sha,
            json.dumps(draft["summary"], ensure_ascii=False),
            json.dumps(draft["entries"], ensure_ascii=False), draft["preview"],
            redacted_instruction or "",
        )
        sid = submissions.create_submission(
            settings, text, findings, sha, kind, original_name, policy=policy,
            session_id=session_id, report_id=report_id,
            instruction=instruction, instruction_findings=instruction_findings,
            is_file=is_file, review_layout=review_layout,
        )
        db.update_report(report_id, submission_id=sid)
        row = db.get_submission(sid)
        return {"pending_confirmation": True, "report_id": report_id,
                **submissions.view(settings, row)}

    # 默认模式（gate=never）：按默认动作直接处理，无等待确认。
    try:
        result = await finalize_mod.finalize(
            settings, creds, text=text, sha=sha, kind=kind, original_name=original_name,
            findings=findings, decisions=None, engine=engine, policy=policy,
            session_id=session_id, instruction=instruction,
            instruction_findings=instruction_findings, sources=sources,
            reuse_source=is_file,
        )
    except finalize_mod.DuplicateSourceError as dup:
        return {"source_id": dup.source_id, "duplicate": True, "message": "内容已存在，未重复处理", "secrets": []}
    # 报告补全保险柜字段并锁定（自动模式：直接执行并保留报告快照，无等待确认）。
    final = report_mod.build_report(
        all_entries, original_name, entries_mod.apply_entries(text, file_entries)[0],
        instruction=result.get("instruction") or "", refs=result.get("refs"),
    )
    from ..security.review import readback_snapshot

    report_id = db.insert_report(
        session_id, None, "auto", "auto", kind, original_name, sha,
        summary=json.dumps(final["summary"], ensure_ascii=False),
        entries=json.dumps(final["entries"], ensure_ascii=False),
        preview=final["preview"],
        review_snapshot=json.dumps(readback_snapshot(
            {"text": text, "instruction": instruction or "", "review_layout": review_layout},
            file_entries, instr_entries), ensure_ascii=False),
        instruction=result.get("instruction") or "",
    )
    db.set_task_report(result["task_id"], report_id)
    result["report_id"] = report_id
    return result
