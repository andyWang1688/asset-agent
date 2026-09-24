"""确认后的落盘与任务编排（闸门直通与确认流程共用）：

应用逐项裁决 → 复扫校验（除放行区间外不得残留 Finding）→
凭证与脱敏 Raw 写入 → 绑定任务来源。正式任务由持久化补偿日志覆盖所有保存。
旧内部调用保留加密挂起队列兼容；新 API 的两种模式均走后台事务。

安全不变量：秘密原文仅允许进入 Private Raw 原件和保险柜；不进 SQLite 明文、
日志/异常或知识模型。
"""
import asyncio
import base64
import json
import re
import sqlite3
import time

from .. import crypto, db
from . import transaction
from ..config import Settings
from ..credentials.base import CredentialError, CredentialStore, SecretPayload
from ..security import redactor
from ..security import entries as entries_mod
from ..security.detectors import ScanEngine, overlaps
from ..security.rules import ACTION_ALLOW, ACTION_STORE, KIND_CREDENTIAL
from ..security.policy import KIND_ALLOWED_ACTIONS

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


def retry_source_id(sha: str) -> int | None:
    """失败轮重投：内容已入库但该来源最新维护任务失败 → 返回可复用的来源 id。
    每轮维护仍生成独立报告与任务；其余情形（处理中/已完成/无任务）继续按重复内容幂等返回。"""
    row = db.get_source_by_sha256(sha)
    if not row or not row["confirmed"]:
        return None
    latest = db.latest_task_for_source(row["id"])
    if latest is not None and latest["status"] == "failed":
        return row["id"]
    return None


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
    """应用裁决生成脱敏文本（store → 私密引用；redact → 占位符；allow → 保留）。
    兼容旧签名；新代码优先使用 entries.apply_entries 以携带用户编辑的名称。"""
    dec = validate_decisions(findings, decisions)
    entries = entries_mod.build_entries(findings, dec)
    return entries_mod.apply_entries(text, entries)


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


async def rescan_guard(engine: ScanEngine, sanitized: str, allowed_spans: list[tuple[int, int]],
                       entries=None) -> None:
    """复扫校验：除“误报放行”区间外，脱敏结果不得残留任何 Finding。
    mask_placeholders 保持等长，放行区间偏移仍然有效。security 增强层失败时回退本地结果。
    命中即阻断（不落盘、不发送），错误信息只含规则名，不含原文。
    只屏蔽本报告登记的精确私密引用，伪造标签不得免检。"""
    valid = None
    if entries is not None:
        valid = {ph for e in entries if (ph := entries_mod._placeholder(e)) is not None}
    masked = redactor.mask_placeholders(sanitized, valid)
    post = await engine.scan_async(masked)
    leftover = [f for f in post if not any(overlaps(f.span, s) for s in allowed_spans)]
    if leftover:
        rules = "、".join(sorted({f.rule for f in leftover})[:8])
        raise GateBlockedError(f"脱敏后仍检测到未处置的敏感内容（命中规则: {rules}），已阻止发送")


async def _store_credentials(
    settings: Settings,
    creds: CredentialStore,
    entries,
    sha: str,
    kind: str,
    original_name: str,
    source_id: int | None = None,
) -> tuple[list[dict], list[tuple[int, str]]]:
    """按解析后的条目写入凭证库：严格使用条目选定的 vault_kind/vault_name/field_name。
    Vaultwarden 失败时进入 AES-GCM 加密队列（任务挂起），队列记录保留条目类型与字段名。
    幂等：按 (值哈希 + 条目类型 + 条目名称 + 字段名) 全量匹配目标身份，
    绝不用「同名条目」吞掉不同秘密，也不复用与报告目标不一致的既有条目。"""
    if not any(e.action == ACTION_STORE for e in entries):
        return [], []
    try:
        items = await creds.list_items()
    except CredentialError:
        if transaction.active.get() is not None:
            raise
        items = None  # 旧内部调用查询失败时仍保留本机已确认的精确映射。
    live_ids = {m.item_id for m in items} if items is not None else None
    known: dict[tuple, dict] = {}
    for r in db.all_source_refs():
        if r.get("saved") and r.get("item_id") and (live_ids is None or r["item_id"] in live_ids):
            key = (r.get("value_hash"), r.get("vault_kind"), r.get("vault_name"), r.get("field_name"))
            known.setdefault(key, {"item_id": r["item_id"]})
    for m in items or []:
        if m.value_hash:
            key = (m.value_hash, m.kind, m.name, m.field_name)
            known.setdefault(key, {"item_id": m.item_id})

    refs_out: list[dict] = []
    pending_pairs: list[tuple[int, str]] = []
    # 目标身份 → 共享条目映射：去重的是保险柜写操作，不是 Finding→引用→保险柜 的映射。
    done_targets: dict[tuple, dict] = {}
    for e in entries:
        if e.action != ACTION_STORE:
            continue
        key = (e.value_hash, e.vault_kind, e.vault_name, e.field_name)
        note = _note(e, original_name, kind, sha)
        entry = {
            "finding_id": e.finding.id,
            "name": e.name,
            "vault_name": e.vault_name,
            "vault_kind": e.vault_kind,
            "field_name": e.field_name,
            "ref_id": e.ref_id,
            "kind": e.finding.kind,
            "rule": e.finding.rule,
            "value_hash": e.value_hash,
        }
        shared = done_targets.get(key)
        if shared is not None:
            # 相同目标共享已创建/挂起的条目：每个 Finding 都返回完整映射，但不再重复写保险柜。
            entry["saved"] = shared.get("saved", False)
            entry["item_id"] = shared.get("item_id")
            if shared.get("pending_id") is not None:
                entry["pending_id"] = shared["pending_id"]
            refs_out.append(entry)
            continue
        matched = known.get(key)
        if matched:
            entry["saved"] = True
            entry["item_id"] = matched["item_id"]
            done_targets[key] = entry
            refs_out.append(entry)
            continue
        payload = _secret_payload(e, note)
        try:
            tx = transaction.active.get()
            item = await tx.create_secret(payload) if tx else await creds.create_secret(payload)
            entry["saved"] = True
            entry["item_id"] = item.item_id
        except CredentialError:
            if transaction.active.get() is not None:
                raise
            blob = crypto.seal(
                settings.local_key(),
                json.dumps(
                    {
                        "name": e.vault_name, "value": e.value, "note": note,
                        "kind": e.vault_kind, "field_name": e.field_name,
                    },
                    ensure_ascii=False,
                ).encode(),
            )
            pid = db.insert_pending(source_id, e.vault_name, sha, blob)
            entry["saved"] = False
            entry["pending_id"] = pid
            pending_pairs.append((pid, e.value))
        done_targets[key] = entry
        refs_out.append(entry)
    return refs_out, pending_pairs


def _note(e, original_name: str, kind: str, sha: str) -> str:
    return (
        f"由资产 Agent 自动保存。来源: {original_name}（{kind}）; 来源哈希: {sha[:16]}; "
        f"规则: {e.finding.rule}; 值哈希: {e.value_hash}; 引用: {e.ref_id}; "
        f"类型: {e.vault_kind}; 字段: {e.field_name}"
    )


def _secret_payload(e, note: str) -> SecretPayload:
    if e.vault_kind == entries_mod.VAULT_SECURE_NOTE:
        return SecretPayload(
            name=e.vault_name, value=e.value, kind="secure_note", note=note,
            fields=[(e.field_name, e.value)],
        )
    return SecretPayload(name=e.vault_name, value=e.value, kind="login", note=note)


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
    session_id: str | None = None,
    edits: dict | None = None,
    instruction: str | None = None,
    instruction_findings: list | None = None,
    sources: dict | None = None,
    reuse_source: bool = False,
    task_id: int | None = None,
    documents: list | None = None,
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
            session_id=session_id, edits=edits, instruction=instruction,
            instruction_findings=instruction_findings, sources=sources,
            reuse_source=reuse_source, task_id=task_id, documents=documents,
        )


_RECLAIM_SECONDS = 600  # 崩溃遗留的 confirmed=0 占位超过 10 分钟可复用


def _parse_db_time(s: str) -> float:
    import datetime

    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return time.time()


def _claim_source(sha: str, kind: str, original_name: str, reuse_source: bool = False) -> tuple[int, bool]:
    """两阶段落库第一步：以 confirmed=0 占位抢占 sha（UNIQUE 跨进程互斥）。
    抢到（或复用崩溃遗留占位）后才允许写凭证；返回 (source_id, 是否新建)。
    失败轮重投复用已确认来源：不新建、不占位，但同样另起报告与任务。"""
    try:
        return db.insert_source(sha, kind, original_name, "", "[]", confirmed=0), True
    except sqlite3.IntegrityError:
        row = db.get_source_by_sha256(sha)
        if row and row["confirmed"]:
            reuse = retry_source_id(sha)
            if reuse_source or reuse is not None:
                return row["id"], False
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
    session_id: str | None = None,
    edits: dict | None = None,
    instruction: str | None = None,
    instruction_findings: list | None = None,
    sources: dict | None = None,
    reuse_source: bool = False,
    task_id: int | None = None,
    documents: list | None = None,
) -> dict:
    instruction_findings = instruction_findings or []
    combined = list(findings) + list(instruction_findings)
    dec = validate_decisions(combined, decisions)
    file_entries, instr_entries = entries_mod.build_all_entries(
        findings, instruction_findings, dec, edits,
        namespace=sha, policy=policy, sources=sources, documents=documents,
    )
    all_entries = file_entries + instr_entries

    if documents and transaction.active.get() is not None:
        return await _finalize_documents(settings, creds, documents, text, sha, all_entries,
                                         file_entries, instr_entries, instruction, engine, task_id)

    # 两阶段落库：占位（confirmed=0，sha UNIQUE 互斥）先于凭证写入
    source_id, claimed = _claim_source(sha, kind, original_name, reuse_source)
    reused = bool(db.get_source(source_id)["confirmed"])
    try:
        if edited_text is not None:
            # 用户修改了脱敏预览：以修改后文本为准，且必须重新扫描（即使原提交无 Finding）
            if not isinstance(edited_text, str) or not edited_text.strip():
                raise ValueError("修改后的脱敏内容为空")
            sanitized = edited_text
            allowed_san = locate_allow_spans(edited_text, findings, dec)
            if engine is None:
                engine = ScanEngine(policy or {}, security_provider=security_provider)
            await rescan_guard(engine, sanitized, allowed_san, entries=all_entries)
        else:
            sanitized, allowed_san = entries_mod.apply_entries(text, file_entries)
            if file_entries:
                if engine is None:
                    engine = ScanEngine(policy or {}, security_provider=security_provider)
                await rescan_guard(engine, sanitized, allowed_san, entries=all_entries)

        # 整理要求（附件附带文字）单独脱敏：不混入文件 Raw，但按同一决定链保存。
        instruction_redacted = ""
        if instruction is not None:
            instruction_redacted, instruction_allowed = entries_mod.apply_entries(instruction, instr_entries)
            if instr_entries:
                if engine is None:
                    engine = ScanEngine(policy or {}, security_provider=security_provider)
                await rescan_guard(engine, instruction_redacted, instruction_allowed, entries=all_entries)

        refs_out, pending_pairs = await _store_credentials(
            settings, creds, all_entries, sha, kind, original_name, source_id=source_id
        )

        rel = f"{sha[:12]}-{_safe_filename(original_name)}"
        raw_path = settings.inbox_dir / rel
        raw_content = (
            f"# 来源: {original_name}\n\n"
            f"<!-- kind: {kind}, sha256: {sha}, ingested_at: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
            f"{sanitized}"
        )
        if not reused:
            tx = transaction.active.get()
            if tx:
                tx.write_raw(raw_path, raw_content)
            else:
                raw_path.write_text(raw_content, encoding="utf-8")

        # 放行区间以最终落盘内容为基准（含文件头偏移）
        offset = len(raw_content) - len(sanitized)
        allowed_spans = [(a + offset, b + offset) for a, b in allowed_san]

        # 两阶段落库第二步：写入路径/引用/放行区间并标记已通过闸门
        if not reused:
            db.update_source_processed(
                source_id, str(raw_path), json.dumps(refs_out, ensure_ascii=False),
                json.dumps([list(s) for s in allowed_spans]), instruction=instruction_redacted or "",
            )
    except Exception:
        if not reused:
            _rollback_claim(sha, source_id, claimed)
        raise

    snapshot = json.dumps({
        "text": raw_content, "instruction": instruction_redacted, "refs": refs_out,
        "allowed_spans": [list(s) for s in allowed_spans],
    }, ensure_ascii=False) if reused else "{}"
    if task_id is None:
        task_id = db.insert_task(source_id, session_id=session_id, input_snapshot=snapshot)
    else:
        db.bind_task_source(task_id, source_id, snapshot)
    if transaction.active.get() is not None:
        db.link_task_source(task_id, source_id, 0)
    db.update_task_status(task_id, "credential_pending" if pending_pairs else "pending")

    return {
        "source_id": source_id,
        "task_id": task_id,
        "secrets": [{"name": r["name"], "saved": r.get("saved", False)} for r in refs_out],
        "secrets_count": len(refs_out),
        "refs": refs_out,
        "instruction": instruction_redacted,
    }


async def _finalize_documents(settings, creds, documents, text, sha, all_entries,
                              file_entries, instr_entries, instruction, engine, task_id):
    from dataclasses import replace
    tx = transaction.active.get()
    instruction_safe, instruction_allowed = entries_mod.apply_entries(instruction or "", instr_entries)
    await rescan_guard(engine, instruction_safe, instruction_allowed, entries=all_entries)
    # 所有文件先复扫，整批通过再产生任何保存副作用。
    prepared = []
    for doc in documents:
        local = [replace(e, finding=replace(e.finding, span=(e.finding.start-doc['start'], e.finding.end-doc['start'])))
                 for e in file_entries if doc['start'] <= e.finding.start < e.finding.end <= doc['end']]
        sanitized, allowed = entries_mod.apply_entries(text[doc['start']:doc['end']], local)
        await rescan_guard(engine, sanitized, allowed, entries=all_entries)
        prepared.append((doc, local, sanitized, allowed))
    ids, all_refs, texts, offsets = [], [], [], []
    for position, (doc, local, sanitized, allowed) in enumerate(prepared):
        # 原件哈希相同但审查结果不同是不同来源；同名不同内容也不会覆盖。
        source_sha = crypto.sha256_hex(doc['sha256'] + sanitized + doc['name'])
        source_id, claimed = _claim_source(source_sha, doc['kind'], doc['name'], True)
        reused = bool(db.get_source(source_id)['confirmed'])
        private_path = tx.archive(doc['name'], base64.b64decode(doc['original']), position, doc['sha256'])
        owned = local + (instr_entries if position == 0 else [])
        refs, _ = await _store_credentials(settings, creds, owned, sha, doc['kind'], doc['name'], source_id)
        for ref in refs:
            entry = next(e for e in owned if e.finding.id == ref['finding_id'])
            finding = entry.finding
            cell_location = next((f"{sheet['name']} · 行 {cell['row']} 列 {cell['col']}"
                                  for sheet in doc['layout'] for cell in sheet['cells']
                                  if cell['start'] <= finding.start < cell['end']), None)
            ref.update(source="整理要求" if entry in instr_entries else doc["name"],
                       private_path=None if entry in instr_entries else private_path,
                       location=cell_location or f"字符 {finding.start + 1}–{finding.end}")
        content = f"# 来源: {doc['name']}\n\n<!-- kind: {doc['kind']} -->\n\n" + sanitized
        header = len(content) - len(sanitized)
        shifted = [[a+header, b+header] for a,b in allowed]
        raw_path = settings.inbox_dir / f"{source_sha[:12]}-{_safe_filename(doc['name'])}.md"
        if not reused:
            tx.write_raw(raw_path, content)
            db.update_source_processed(source_id, str(raw_path), json.dumps(refs, ensure_ascii=False),
                                       json.dumps(shifted), instruction=instruction_safe)
        db.link_task_source(task_id, source_id, position, private_path, doc['sha256'])
        offset = sum(len(t)+2 for t in texts)
        offsets.extend([[a+offset,b+offset] for a,b in shifted])
        ids.append(source_id); all_refs.extend(refs); texts.append(content)
    snapshot = json.dumps(dict(text="\n\n".join(texts), instruction=instruction_safe,
                               refs=all_refs, allowed_spans=offsets), ensure_ascii=False)
    db.bind_task_source(task_id, ids[0], snapshot)
    db.update_task_status(task_id, 'pending')
    return dict(source_id=ids[0], source_ids=ids, task_id=task_id, refs=all_refs,
                secrets_count=len(all_refs), instruction=instruction_safe)
