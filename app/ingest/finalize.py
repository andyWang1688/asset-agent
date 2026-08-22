"""确认后的落盘与任务编排（闸门直通与确认流程共用）：

应用逐项裁决 → 复扫校验（除放行区间外不得残留 Finding）→
凭证写入（失败入 AES-GCM 加密队列，任务挂起）→ 脱敏 Raw 落盘 → 建来源与任务。

安全不变量：秘密原文不落盘、不进 SQLite 明文、不进日志/异常、不进云端模型。
"""
import asyncio
import json
import re
import sqlite3
import time

from .. import crypto, db
from ..config import Settings
from ..credentials.base import CredentialError, CredentialStore, SecretPayload
from ..security import redactor
from ..security.detectors import ScanEngine, overlaps
from ..security.rules import ACTION_ALLOW, ACTION_STORE, KIND_CREDENTIAL
from ..security.policy import KIND_ALLOWED_ACTIONS

_VALUE_SENTINEL = "\x00ref\x00"
_PLACEHOLDER_SPLIT = re.compile(r"(\[SECRET_REF:[^\]]+\]|\[REDACTED:[^\]]+\])")

# 单进程内的落盘互斥：查重→凭证写入→insert_source 是一个原子窗口，
# 防止并发确认竞态重复创建 Vaultwarden 条目。按事件循环取锁（测试/运行各用各的循环）。
_finalize_locks: dict = {}


def _finalize_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _finalize_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _finalize_locks[loop] = lock
    return lock


class GateBlockedError(ValueError):
    """复扫发现未处置 Finding（消息不得包含秘密原文）。"""


class DuplicateSourceError(Exception):
    """相同内容已入库（幂等路径）。"""

    def __init__(self, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(f"内容已存在（来源 #{source_id}）")


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name or "pasted.txt")[:80] or "pasted.txt"


def validate_decisions(findings, decisions: dict | None) -> dict:
    """裁决必须覆盖全部 Finding；未知 id 或非法动作直接报错（不落盘、不发送）。"""
    if decisions is None:
        return {f.id: f.suggested_action for f in findings}
    if not isinstance(decisions, dict):
        raise ValueError("decisions 必须为映射")
    ids = {f.id for f in findings}
    unknown = [fid for fid in decisions if fid not in ids]
    if unknown:
        raise ValueError(f"存在未知 Finding 裁决: {', '.join(sorted(unknown)[:3])}")
    missing = [f.id for f in findings if f.id not in decisions]
    if missing:
        raise ValueError(f"仍有 {len(missing)} 个 Finding 未处置，已阻止发送（未调用云端模型）")
    out = {}
    for f in findings:
        action = decisions[f.id]
        if action not in KIND_ALLOWED_ACTIONS[f.kind]:
            raise ValueError(f"Finding（{f.rule}）不允许动作 {action}")
        out[f.id] = action
    return out


def apply_decisions(text: str, findings, decisions: dict) -> tuple[str, list[tuple[int, int]]]:
    """应用裁决：store → [SECRET_REF:name]；redact → [REDACTED:rule]；allow → 保留原文。
    返回 (最终文本, 放行区间列表（相对最终文本）)。"""
    names = redactor.ref_names(findings)

    def _placeholder(f, action):
        if action == ACTION_STORE and f.kind == KIND_CREDENTIAL:
            return f"[SECRET_REF:{names.get(f.value, f.rule)}]"
        return f"[REDACTED:{f.rule}]"

    # 1) 全部 Finding 按 span 替换（自右向左，偏移稳定；key=value 连键名一并替换）
    for f in sorted(findings, key=lambda x: -x.span[0]):
        action = decisions.get(f.id, f.suggested_action)
        if action == ACTION_ALLOW:
            continue
        text = text[: f.span[0]] + _placeholder(f, action) + text[f.span[1] :]
    # 2) 值兜底全量替换（同一值在其他位置重复出现，阈值与确认视图一致）；
    #    仅在非占位符段内执行，避免占位符自嵌套
    for f in sorted(
        [x for x in findings if x.value and redactor.should_mask_value(x.value)],
        key=lambda x: -len(x.value),
    ):
        action = decisions.get(f.id, f.suggested_action)
        if action == ACTION_ALLOW:
            continue
        ph = _placeholder(f, action)
        if f.value in ph or f.value not in text:
            continue
        sentinel = _VALUE_SENTINEL + crypto.sha256_hex(f.value)[:16] + "\x00"
        parts = _PLACEHOLDER_SPLIT.split(text)
        for i, part in enumerate(parts):
            if i % 2 == 0:
                parts[i] = part.replace(f.value, sentinel)
        text = "".join(parts).replace(sentinel, ph)
    # 3) 放行区间：在最终文本中按值定位
    return text, locate_allow_spans(text, findings, decisions)


def locate_allow_spans(text: str, findings, decisions: dict) -> list[tuple[int, int]]:
    """按值在给定文本中定位“误报放行”区间（短值就近匹配，避免错位）。"""
    allowed: list[tuple[int, int]] = []
    cursor = 0
    for f in sorted(
        [x for x in findings if decisions.get(x.id, x.suggested_action) == ACTION_ALLOW],
        key=lambda x: x.span[0],
    ):
        i = text.find(f.value, cursor)
        if i >= 0:
            allowed.append((i, i + len(f.value)))
            cursor = i + len(f.value)
    return allowed


async def rescan_guard(engine: ScanEngine, sanitized: str, allowed_spans: list[tuple[int, int]]) -> None:
    """复扫校验：除“误报放行”区间外，脱敏结果不得残留任何 Finding。
    mask_placeholders 保持等长，放行区间偏移仍然有效。security 增强层失败时回退本地结果。
    命中即阻断（不落盘、不发送），错误信息只含规则名，不含原文。"""
    masked = redactor.mask_placeholders(sanitized)
    post = await engine.scan_async(masked)
    leftover = [f for f in post if not any(overlaps(f.span, s) for s in allowed_spans)]
    if leftover:
        rules = "、".join(sorted({f.rule for f in leftover})[:8])
        raise GateBlockedError(f"脱敏后仍检测到未处置的敏感内容（命中规则: {rules}），已阻止发送")


async def _store_credentials(
    settings: Settings,
    creds: CredentialStore,
    findings,
    decisions: dict,
    sha: str,
    kind: str,
    original_name: str,
    source_id: int | None = None,
) -> tuple[list[dict], list[tuple[int, str]]]:
    """把 store 裁决写入凭证库。Vaultwarden 失败时进入 AES-GCM 加密队列（任务挂起）。
    幂等：凭证库已有 note 以“由资产 Agent 自动保存”（或旧版“由资产助手自动保存”）开头的同名条目时复用，不重复创建。"""
    names = redactor.ref_names(findings)
    known: dict[str, dict] = {}
    try:
        for m in await creds.list_items():
            if (m.note or "").startswith(("由资产 Agent 自动保存", "由资产助手自动保存")):
                known.setdefault(m.name, {"name": m.name, "item_id": m.item_id})
    except CredentialError:
        known = {}  # 元数据不可用不阻断：写入时按失败入队

    refs_out: list[dict] = []
    pending_pairs: list[tuple[int, str]] = []
    done_values: set[str] = set()
    for f in findings:
        if decisions.get(f.id, f.suggested_action) != ACTION_STORE or f.kind != KIND_CREDENTIAL:
            continue
        if f.value in done_values:
            continue
        done_values.add(f.value)
        name = names.get(f.value, f.rule)
        entry = {"name": name, "kind": f.kind, "rule": f.rule, "value_hash": crypto.sha256_hex(f.value)[:16]}
        if name in known:
            entry["saved"] = True
            entry["item_id"] = known[name]["item_id"]
            refs_out.append(entry)
            continue
        note = f"由资产 Agent 自动保存。来源: {original_name}（{kind}）; 来源哈希: {sha[:16]}; 规则: {f.rule}"
        payload = SecretPayload(name=name, value=f.value, kind="login", note=note)
        try:
            item = await creds.create_secret(payload)
            entry["saved"] = True
            entry["item_id"] = item.item_id
        except CredentialError:
            blob = crypto.seal(
                settings.local_key(),
                json.dumps({"name": name, "value": f.value, "note": note}, ensure_ascii=False).encode(),
            )
            pid = db.insert_pending(source_id, name, sha, blob)
            entry["saved"] = False
            entry["pending_id"] = pid
            pending_pairs.append((pid, f.value))
        refs_out.append(entry)
        known[name] = {"name": name, "item_id": entry.get("item_id", "")}
    return refs_out, pending_pairs


async def finalize(
    settings: Settings,
    creds: CredentialStore,
    *,
    text: str,
    sha: str,
    kind: str,
    original_name: str,
    findings: list,
    decisions: dict | None = None,
    engine: ScanEngine | None = None,
    policy: dict | None = None,
    edited_text: str | None = None,
    security_provider=None,
) -> dict:
    """裁决 → 复扫 → 凭证 → 落盘 → 任务。重复内容幂等（由调用方先查重）。
    edited_text：用户在确认页修改过的脱敏预览——必须重新扫描，
    除“误报放行”区间外残留 Finding 即阻断（修改后必须重新扫描）。
    全程持进程内互斥锁：并发确认/直通时凭证不会重复写入。"""
    async with _finalize_lock():
        return await _finalize_locked(
            settings, creds, text=text, sha=sha, kind=kind, original_name=original_name,
            findings=findings, decisions=decisions, engine=engine, policy=policy,
            edited_text=edited_text, security_provider=security_provider,
        )


_RECLAIM_SECONDS = 600  # 崩溃遗留的 confirmed=0 占位超过 10 分钟可复用


def _parse_db_time(s: str) -> float:
    import datetime

    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return time.time()


def _claim_source(sha: str, kind: str, original_name: str) -> tuple[int, bool]:
    """两阶段落库第一步：以 confirmed=0 占位抢占 sha（UNIQUE 跨进程互斥）。
    抢到（或复用崩溃遗留占位）后才允许写凭证；返回 (source_id, 是否新建)。"""
    try:
        return db.insert_source(sha, kind, original_name, "", "[]", confirmed=0), True
    except sqlite3.IntegrityError:
        row = db.get_source_by_sha256(sha)
        if row and row["confirmed"]:
            raise DuplicateSourceError(row["id"]) from None
        if row and time.time() - _parse_db_time(row["created_at"]) > _RECLAIM_SECONDS:
            return row["id"], False  # 复用崩溃遗留占位（幂等重试）
        if row:
            raise DuplicateSourceError(row["id"]) from None  # 跨进程进行中的确认
        raise


def _rollback_claim(sha: str, source_id: int, claimed: bool) -> None:
    """占位后失败：清除待处理凭证与本轮新建的占位行（已写入 Vaultwarden 的条目
    由“同名同来源复用”逻辑在重试时幂等接管）。"""
    db.delete_pending_by_source(source_id)
    if claimed:
        db.delete_source_by_sha256(sha)


async def _finalize_locked(
    settings: Settings,
    creds: CredentialStore,
    *,
    text: str,
    sha: str,
    kind: str,
    original_name: str,
    findings: list,
    decisions: dict | None,
    engine: ScanEngine | None,
    policy: dict | None,
    edited_text: str | None,
    security_provider=None,
) -> dict:
    dec = validate_decisions(findings, decisions)

    # 两阶段落库：占位（confirmed=0，sha UNIQUE 互斥）先于凭证写入
    source_id, claimed = _claim_source(sha, kind, original_name)
    try:
        if edited_text is not None:
            # 用户修改了脱敏预览：以修改后文本为准，且必须重新扫描（即使原提交无 Finding）
            if not isinstance(edited_text, str) or not edited_text.strip():
                raise ValueError("修改后的脱敏内容为空")
            sanitized = edited_text
            allowed_san = locate_allow_spans(edited_text, findings, dec)
            if engine is None:
                engine = ScanEngine(policy or {}, security_provider=security_provider)
            await rescan_guard(engine, sanitized, allowed_san)
        else:
            sanitized, allowed_san = apply_decisions(text, findings, dec)
            if findings:
                if engine is None:
                    engine = ScanEngine(policy or {}, security_provider=security_provider)
                await rescan_guard(engine, sanitized, allowed_san)

        refs_out, pending_pairs = await _store_credentials(
            settings, creds, findings, dec, sha, kind, original_name, source_id=source_id
        )

        rel = f"{sha[:12]}-{_safe_filename(original_name)}"
        raw_path = settings.inbox_dir / rel
        raw_content = (
            f"# 来源: {original_name}\n\n"
            f"<!-- kind: {kind}, sha256: {sha}, ingested_at: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
            f"{sanitized}"
        )
        raw_path.write_text(raw_content, encoding="utf-8")

        # 放行区间以最终落盘内容为基准（含文件头偏移）
        allowed_spans: list[tuple[int, int]] = []
        cursor = 0
        for f in sorted([x for x in findings if dec.get(x.id) == ACTION_ALLOW], key=lambda x: x.span[0]):
            i = raw_content.find(f.value, cursor)
            if i >= 0:
                allowed_spans.append((i, i + len(f.value)))
                cursor = i + len(f.value)

        # 两阶段落库第二步：写入路径/引用/放行区间并标记已通过闸门
        db.update_source_processed(
            source_id,
            str(raw_path),
            json.dumps(refs_out, ensure_ascii=False),
            json.dumps([list(s) for s in allowed_spans]),
        )
    except Exception:
        _rollback_claim(sha, source_id, claimed)
        raise

    task_id = db.insert_task(source_id)
    db.update_task_status(task_id, "credential_pending" if pending_pairs else "pending")

    return {
        "source_id": source_id,
        "task_id": task_id,
        "secrets": [{"name": r["name"], "saved": r.get("saved", False)} for r in refs_out],
        "secrets_count": len(refs_out),
    }
