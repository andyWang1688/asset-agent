"""接收与任务编排：内存扫描 → 闸门（有 Finding 时进入待确认加密队列）→ 落盘 → 编译任务。

安全不变量：知识模型只接收安全处理后的资料；确认前仅加密暂存。
确认后由后台任务保存原件、敏感值、脱敏 Raw 和 Wiki。
"""
import base64
import hashlib
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
    files: list[tuple[str, bytes]] | None = None,
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
    documents = []
    review_layout = []
    uploads = files or ([(filename or "upload.txt", data or b"")] if text is None else [])
    if uploads:
        if len(uploads) > 20 or sum(len(content) for _, content in uploads) > settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"一批最多 20 个文件，总大小不超过 {settings.max_upload_mb}MB")
        identities = [(name, hashlib.sha256(content).hexdigest()) for name, content in uploads]
        if len(identities) != len(set(identities)):
            raise ValueError("同一文件被重复选择，请移除重复附件")
        parts = []
        offset = 0
        for index, (name, content) in enumerate(uploads):
            layout = []
            try:
                file_kind, extracted = parse_upload(name, content, settings.max_upload_mb, layout)
            except ValueError as error:
                raise ValueError(f"第 {index + 1} 个文件：{error}") from None
            documents.append(dict(id=f"file-{index}" if len(uploads) > 1 else "document", name=name, kind=file_kind,
                                  start=offset, end=offset + len(extracted), layout=layout,
                                  original=base64.b64encode(content).decode(),
                                  sha256=hashlib.sha256(content).hexdigest()))
            parts.append(extracted)
            offset += len(extracted) + 2
        text = "\n\n".join(parts)
        if len(text) > 2_000_000:
            raise ValueError("本批提取文本过长，请拆分后上传")
        kind = documents[0]["kind"] if len(documents) == 1 else "batch"
        original_name = documents[0]["name"]
        instruction = (instruction or "").strip() or None
        is_file = True
        review_layout = documents[0]["layout"] if len(documents) == 1 else []
    else:
        kind, text = "text", (text or "").strip()
        original_name = "pasted.txt"
        instruction = None
        is_file = False
    if not text:
        raise ValueError("内容为空")

    sha = crypto.sha256_hex(json.dumps([(d["sha256"], d["name"]) for d in documents])) if documents else crypto.sha256_hex(text)
    store = policy_store or PolicyStore(settings.policy_file)
    policy = store.load()

    def _warn(msg: str) -> None:
        db.log_security("detector_warning", msg)

    engine = ScanEngine(policy, on_warning=_warn, security_provider=security_provider)
    # 输入先在内存扫描：任何介质写入之前；基础检测器失败必须阻断。
    # security 增强层失败仅回退本地检测结果（可选层）。
    try:
        if documents:
            findings = []
            for doc in documents:
                hits = await engine.scan_async(text[doc['start']:doc['end']])
                findings.extend(replace(f, id=f"{doc['id']}:{f.id}",
                                        span=(f.start+doc['start'], f.end+doc['start'])) for f in hits)
        else:
            findings = await engine.scan_async(text)
    except Exception as e:  # 基础检测器失败：阻断（绝不带着未扫描的明文继续）
        db.log_security("detector_failed", f"检测器失败已阻断提交: {type(e).__name__}")
        raise ValueError("检测器失败，本次提交已阻断（未保存、未发送）") from e

    # 文件名独立扫描；模型与报告只接收安全名称，原件使用安全名称保留扩展名。
    for document in documents:
        try:
            hits = await engine.scan_async(document["name"])
        except Exception as e:
            raise ValueError("文件名检测失败，本批提交已阻断") from e
        if hits:
            document["name"], _ = finalize_mod.apply_decisions(
                document["name"], hits, {f.id: "redact" for f in hits})
    if documents:
        original_name = documents[0]["name"] + (f" 等 {len(documents)} 个文件" if len(documents) > 1 else "")

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
        namespace=sha, policy=policy, sources=sources, documents=documents,
    )
    all_entries = file_entries + instr_entries
    preview, _ = entries_mod.apply_entries(text, file_entries)
    if not is_file:
        original_name = text_source_name(preview)
    if instruction is not None:
        redacted_instruction, _ = entries_mod.apply_entries(instruction, instr_entries)
    existing_sub = db.submission_by_sha256(submissions.submission_key(sha, instruction), session_id)
    if existing_sub:
        if existing_sub['status'] == 'processing':
            task = db.task_for_report(existing_sub['report_id'])
            return dict(submission_id=existing_sub['id'], report_id=existing_sub['report_id'], task_id=task['id'])
        if gate != "always":
            raise ValueError("同一批资料已在等待确认，请先处理已有报告")
        return {"pending_confirmation": True,
                **submissions.view(settings, existing_sub)}
    if db.submission_count_waiting() >= settings.pending_submission_limit:
        raise ValueError("待确认队列已满，请先处理或取消已有提交")
    draft = report_mod.build_report(all_entries, original_name, preview,
                                    instruction=redacted_instruction)
    report_id = db.insert_report(
        session_id, None, "pending", "confirm" if gate == "always" else "auto", kind, original_name, sha,
        json.dumps(draft["summary"], ensure_ascii=False),
        json.dumps(draft["entries"], ensure_ascii=False), draft["preview"],
        redacted_instruction or "",
    )
    sid = submissions.create_submission(
        settings, text, findings, sha, kind, original_name, policy=policy,
        session_id=session_id, report_id=report_id,
        instruction=instruction, instruction_findings=instruction_findings,
        is_file=is_file, review_layout=review_layout, documents=documents,
    )
    db.update_report(report_id, submission_id=sid)
    row = db.get_submission(sid)
    if gate != "always":
        from ..security import plans
        return plans.enqueue(settings, store, sid, decisions_default, session_id=session_id,
                             provider=knowledge_provider_getter())
    return {"pending_confirmation": True, "report_id": report_id,
            **submissions.view(settings, row)}
