"""确认闸门：待确认提交的加密暂存、视图、确认与取消。

原文只在内存中短暂出现，随即以 AES-256-GCM（密钥来自 PENDING_QUEUE_KEY_FILE，
未配置时回退本地密钥）加密进入等待确认队列，TTL 7 天（由 Worker 清理）。
确认前：不写 Raw、不建任务、不调云端模型、不写 Vaultwarden。
取消/过期：密文销毁，仅留审计元数据（绝不含秘密原文）。
"""
import json
import time

from .. import crypto, db
from ..config import Settings
from ..credentials.base import CredentialStore
from ..ingest.finalize import DuplicateSourceError, finalize
from ..security.detectors import ScanEngine
from ..security.policy import KIND_ALLOWED_ACTIONS, PolicyStore
from ..security.rules import Finding, KINDS

PAYLOAD_VERSION = 1
_CONTEXT_WINDOW = 60
_MASK = "⟨已掩码⟩"


class SubmissionError(ValueError):
    """确认闸门错误（消息不含秘密原文）。"""


def finding_to_dict(f: Finding) -> dict:
    return {
        "id": f.id,
        "kind": f.kind,
        "rule": f.rule,
        "span": list(f.span),
        "confidence": f.confidence,
        "evidence": f.evidence,
        "suggested_action": f.suggested_action,
        "detector": f.detector,
        "value": f.value,
        "key_hint": f.key_hint,
    }


def finding_from_dict(d: dict) -> Finding:
    return Finding(
        id=d["id"],
        kind=d["kind"],
        rule=d["rule"],
        span=(int(d["span"][0]), int(d["span"][1])),
        confidence=float(d["confidence"]),
        evidence=d.get("evidence", ""),
        suggested_action=d.get("suggested_action", "redact"),
        detector=d.get("detector", ""),
        value=d.get("value", ""),
        key_hint=d.get("key_hint"),
    )


def summary_counts(findings: list[Finding]) -> dict:
    out = {k: 0 for k in KINDS}
    for f in findings:
        out[f.kind] = out.get(f.kind, 0) + 1
    return out


def _audit_decision(f: Finding, action: str) -> None:
    db.log_security(
        "finding_decision",
        json.dumps(
            {
                "rule": f.rule,
                "kind": f.kind,
                "action": action,
                "value_hash": crypto.sha256_hex(f.value)[:16],
                "span": list(f.span),
            },
            ensure_ascii=False,
        ),
    )


def create_submission(settings: Settings, text: str, findings: list[Finding], sha: str,
                      kind: str, original_name: str, policy: dict | None = None) -> int:
    payload = {
        "version": PAYLOAD_VERSION,
        "text": text,
        "sha256": sha,
        "kind": kind,
        "original_name": original_name,
        "findings": [finding_to_dict(f) for f in findings],
        # 提交时策略快照：确认复扫使用快照，防止等待期间策略被放宽而漏检
        "policy": policy or {},
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    blob = crypto.seal(
        settings.queue_key(),
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    summary = json.dumps(summary_counts(findings))
    db.delete_stale_submissions(sha)  # 同内容取消/过期后可重新提交（sha256 UNIQUE）
    sid = db.insert_submission(sha, kind, original_name, blob, summary)
    db.log_security(
        "submission_created",
        f"提交 #{sid}（来源哈希 {sha[:16]}）进入确认闸门: {summary}",
    )
    return sid


def _decrypt(settings: Settings, row) -> dict:
    try:
        raw = crypto.open_sealed(settings.queue_key(), row["payload"])
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("version") != PAYLOAD_VERSION:
            raise SubmissionError("提交数据版本不兼容")
        return payload
    except SubmissionError:
        raise
    except Exception as e:
        db.log_security("submission_corrupt", f"提交 #{row['id']} 无法解密: {type(e).__name__}")
        raise SubmissionError("提交无法解密（密钥变更或数据损坏），请取消后重新提交") from e


def masked_context(text: str, findings: list[Finding], target: Finding, window: int = _CONTEXT_WINDOW) -> str:
    """目标 Finding 的掩码上下文：绝不含原文。
    1) 窗口内与窗口相交的所有 Finding 片段（含部分重叠）按 span 掩码；
    2) 兜底：所有 Finding 值在窗口内的其他出现位置一并掩码
       （与完整脱敏预览的兜底替换行为一致，防止同一秘密值在别处重复出现时泄漏）。"""
    start = max(0, target.span[0] - window)
    end = min(len(text), target.span[1] + window)
    seg = text[start:end]
    for f in sorted(findings, key=lambda x: -x.span[0]):
        if f.span[0] < end and f.span[1] > start:  # 相交即掩码（含部分重叠）
            lo = max(f.span[0], start)
            hi = min(f.span[1], end)
            seg = seg[: lo - start] + _MASK + seg[hi - start :]
    from .redactor import should_mask_value

    for f in sorted(findings, key=lambda x: -len(x.value or "")):
        if f.value and should_mask_value(f.value):
            seg = seg.replace(f.value, _MASK)
    return seg


def view(settings: Settings, row) -> dict:
    """确认页数据：分类汇总、逐项 Finding（掩码上下文）、完整脱敏预览。绝不含秘密原文。"""
    payload = _decrypt(settings, row)
    text = payload["text"]
    findings = [finding_from_dict(d) for d in payload.get("findings") or []]
    counts = summary_counts(findings)

    from ..ingest.finalize import apply_decisions

    preview, _ = apply_decisions(text, findings, {f.id: f.suggested_action for f in findings})

    findings_out = []
    for f in findings:
        findings_out.append(
            {
                "id": f.id,
                "kind": f.kind,
                "rule": f.rule,
                "confidence": round(f.confidence, 3),
                "evidence": f.evidence,
                "suggested_action": f.suggested_action,
                "allowed_actions": list(KIND_ALLOWED_ACTIONS[f.kind]),
                "detector": f.detector,
                "context": masked_context(text, findings, f),
            }
        )
    created = row["created_at"] or ""
    return {
        "submission_id": row["id"],
        "status": row["status"],
        "original_name": payload.get("original_name", ""),
        "created_at": created,
        "summary": counts,
        "findings": findings_out,
        "preview": preview,
    }


async def confirm(settings: Settings, creds: CredentialStore, policy_store: PolicyStore,
                  submission_id: int, decisions: dict, edited_text: str | None = None,
                  security_provider=None, knowledge_provider_getter=None) -> dict:
    """逐项裁决 → 复扫校验 → 落盘/凭证/任务。仍有未处置 Finding 时不得调用云端模型。
    edited_text：用户在确认页修改过的脱敏预览，提交后必须重新扫描。
    knowledge 模型未配置时在创建任务前拒绝确认（提交保持待确认，配置后重试）。"""
    row = db.get_submission(submission_id)
    if not row or row["status"] != "waiting":
        raise SubmissionError("提交不存在或已处理")
    # knowledge 必配闸门（fail-closed）：未配置/激活时不落盘、不建编译任务，待确认记录保留
    if knowledge_provider_getter is None:
        from ..llm.provider import get_active_provider

        knowledge_provider_getter = lambda: get_active_provider(settings)
    if knowledge_provider_getter() is None:
        raise SubmissionError(
            "未配置知识库模型：无法创建编译任务，本次确认已阻止"
            "（提交保持待确认，请先在「设置」页配置并激活知识库模型后重试）"
        )
    payload = _decrypt(settings, row)
    text = payload["text"]
    sha = payload["sha256"]
    kind = payload["kind"]
    original_name = payload["original_name"]
    findings = [finding_from_dict(d) for d in payload.get("findings") or []]

    if edited_text is not None and len(edited_text) > settings.max_upload_mb * 1024 * 1024:
        raise SubmissionError("修改后的脱敏内容超过上传上限")

    existing = db.get_source_by_sha256(sha)
    if existing and existing["confirmed"]:
        # 已处理内容幂等返回；confirmed=0 的占位交由 finalize 的 claim 阶段处理（复用/冲突）
        db.resolve_submission(submission_id, "confirmed")
        return {"source_id": existing["id"], "duplicate": True,
                "message": "内容已存在，未重复处理", "secrets": []}

    # 使用提交时的策略快照做确认与复扫（防等待期间策略放宽）；缺失时回退当前策略
    snapshot = payload.get("policy")
    policy = snapshot if isinstance(snapshot, dict) and snapshot else policy_store.load()
    engine = ScanEngine(policy, security_provider=security_provider)
    try:
        result = await finalize(
            settings, creds, text=text, sha=sha, kind=kind, original_name=original_name,
            findings=findings, decisions=decisions, engine=engine, policy=policy,
            edited_text=edited_text, security_provider=security_provider,
        )
    except DuplicateSourceError as dup:
        db.resolve_submission(submission_id, "confirmed")
        db.log_security("submission_confirmed", f"提交 #{submission_id} 内容已存在（来源 #{dup.source_id}），幂等跳过")
        return {"source_id": dup.source_id, "duplicate": True,
                "message": "内容已存在，未重复处理", "secrets": []}
    except ValueError as e:
        # 未处置/复扫残留：不落盘、不发送；审计只记规则名
        db.log_security("confirm_rejected", f"提交 #{submission_id} 确认被拒: {type(e).__name__}")
        raise SubmissionError(str(e)) from e

    db.resolve_submission(submission_id, "confirmed")  # 清除密文，销毁临时明文
    for f in findings:
        _audit_decision(f, decisions.get(f.id, f.suggested_action))
    db.log_security("submission_confirmed", f"提交 #{submission_id} 已确认，来源 #{result['source_id']}")
    return result


def cancel(settings: Settings, submission_id: int) -> None:
    """拒绝：不解密、不调模型、不写 Vaultwarden；直接销毁暂存密文。"""
    row = db.get_submission(submission_id)
    if not row or row["status"] != "waiting":
        raise SubmissionError("提交不存在或已处理")
    db.resolve_submission(submission_id, "cancelled")
    db.log_security("submission_cancelled", f"提交 #{submission_id} 已取消，明文已销毁")
