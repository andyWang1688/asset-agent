"""安全报告条目：从 Finding + 裁决 + 用户编辑解析出最终条目，作为脱敏与写保险柜的唯一事实源。

Finding 原值、真实 span、引用 ID 由程序控制，客户端只能改固定字段
（类型/可读名称/说明/保存动作/保险柜条目类型与名称）。可编辑字符串统一做安全校验，
不能把秘密挪进标题/说明再明文落库。
"""
from dataclasses import dataclass, replace

from ..crypto import sha256_hex
from . import redactor
from .rules import (
    ACTION_ALLOW,
    ACTION_REDACT,
    ACTION_STORE,
    KIND_CREDENTIAL,
    KINDS,
    Finding,
    scan_text,
)

VAULT_LOGIN = "login"
VAULT_SECURE_NOTE = "secure_note"
VAULT_KINDS = (VAULT_LOGIN, VAULT_SECURE_NOTE)

# 密码类键 → Login；其余（token/api_key/pii/unknown）→ Secure Note 字段
_PASSWORD_KEYS = {"password", "passwd", "pwd", "密码", "口令"}
_MAX_EDITABLE = 200


@dataclass
class Entry:
    finding: Finding
    source: str          # 来源定位（原文件名 / 整理要求）
    type: str            # 敏感类型（credential/pii/unknown_suspect），可编辑
    action: str          # store / redact / allow
    name: str            # 可读名称（占位符 + 报告）
    description: str     # 说明（仅元数据，不落原文）
    vault_kind: str      # login / secure_note
    vault_name: str      # 保险柜条目名称
    field_name: str      # Secure Note 字段名
    ref_id: str          # 稳定引用 ID（程序生成，与值无可逆关系）

    @property
    def value(self) -> str:
        return self.finding.value

    @property
    def value_hash(self) -> str:
        return sha256_hex(self.finding.value)[:16]


def default_vault_kind(kind: str, key_hint: str | None) -> str:
    """程序给出的默认保险柜条目类型：密码类键 → login；其余 → secure_note。"""
    if kind == KIND_CREDENTIAL and (key_hint or "").lower() in _PASSWORD_KEYS:
        return VAULT_LOGIN
    return VAULT_SECURE_NOTE


def _clean_editable(value, default: str, field_label: str, findings, policy) -> str:
    """校验并返回可编辑字符串：空值回退默认；超长/含敏感值/含新秘密 → 拒绝。"""
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field_label} 必须为字符串")
    value = value.strip()
    if not value:
        return default
    if len(value) > _MAX_EDITABLE:
        raise ValueError(f"{field_label} 长度超限")
    # 不能把秘密值挪进元数据，也不能写入新的敏感内容
    for f in findings:
        if f.value and len(f.value) >= 4 and f.value in value:
            raise ValueError(f"{field_label} 不得包含敏感值")
    if scan_text(value, policy):
        raise ValueError(f"{field_label} 不得包含敏感内容")
    return value


def build_entries(findings: list[Finding], decisions: dict, edits: dict | None = None,
                  namespace: str = "", policy: dict | None = None,
                  sources: dict | None = None, known_ids: set | None = None) -> list[Entry]:
    """解析最终条目：decisions 覆盖动作；edits 覆盖可编辑字段。
    decisions 必须已通过 validate_decisions（覆盖全部 Finding、动作合法）。"""
    names = redactor.ref_names(findings)
    edits = edits or {}
    ids = known_ids if known_ids is not None else {f.id for f in findings}
    unknown = [fid for fid in edits if fid not in ids]
    if unknown:
        raise ValueError(f"存在未知 Finding 编辑: {', '.join(sorted(unknown)[:3])}")

    entries: list[Entry] = []
    for f in findings:
        action = decisions[f.id]
        e = edits.get(f.id) or {}
        source = (sources or {}).get(f.id, "")
        name = _clean_editable(e.get("name"), names.get(f.value, f.rule), "可读名称", findings, policy)
        description = _clean_editable(e.get("description"), "", "说明", findings, policy)
        type_ = e.get("type") or f.kind
        if type_ not in KINDS:
            raise ValueError(f"类型必须是 {KINDS} 之一")
        vault_kind = e.get("vault_kind") or default_vault_kind(type_, f.key_hint)
        if vault_kind not in VAULT_KINDS:
            raise ValueError(f"保险柜条目类型必须是 {VAULT_KINDS} 之一")
        vault_name = _clean_editable(e.get("vault_name"), name, "保险柜条目名称", findings, policy)
        field_name = _clean_editable(e.get("field_name"), name, "字段名称", findings, policy)
        entries.append(
            Entry(
                finding=f, source=source, type=type_, action=action, name=name, description=description,
                vault_kind=vault_kind, vault_name=vault_name, field_name=field_name,
                ref_id=redactor.ref_id_for(f, namespace),
            )
        )
    return entries


def build_all_entries(findings, instruction_findings, decisions, edits=None,
                      namespace="", policy=None, sources=None, documents=None):
    """分别构建文件条目与整理要求条目（不同命名空间，避免引用 ID 跨来源碰撞）。"""
    known_ids = {f.id for f in list(findings) + list(instruction_findings)}
    if documents:
        file_entries = []
        for doc in documents:
            group = [f for f in findings if doc['start'] <= f.start < f.end <= doc['end']]
            doc_namespace = doc['sha256'] + "\x00" + doc['name']
            group_entries = build_entries(group, decisions, edits, namespace=doc_namespace,
                                          policy=policy, sources=sources, known_ids=known_ids)
            for entry in group_entries:
                f = entry.finding
                # 使用文件内坐标，报告 Finding ID 仍保留本批定位信息。
                local_id = f"{f.detector}:{f.rule}:{f.start-doc['start']}:{f.end-doc['start']}"
                entry.ref_id = redactor.ref_id_for(replace(f, id=local_id), doc_namespace)
            file_entries.extend(group_entries)
    else:
        file_entries = build_entries(findings, decisions, edits, namespace=namespace,
                                     policy=policy, sources=sources, known_ids=known_ids)
    instr_entries = build_entries(instruction_findings, decisions, edits,
                                  namespace=namespace + ":instr",
                                  policy=policy, sources=sources, known_ids=known_ids)
    return file_entries, instr_entries


def _placeholder(e: Entry) -> str | None:
    if e.action == ACTION_ALLOW:
        return None
    if e.action == ACTION_STORE:
        return redactor.private_ref(e.name, e.ref_id)
    return redactor.redact_ref(e.finding.rule)


_VALUE_SENTINEL = "\x00ref\x00"


def apply_entries(text: str, entries: list[Entry], *, repeated_entries: list[Entry] | None = None,
                  preview_spans: list[dict] | None = None) -> tuple[str, list[tuple[int, int]]]:
    """按条目脱敏：store → [🔒 name](private:ref_id)；redact → [REDACTED:rule]；allow → 保留。
    返回 (脱敏文本, 放行区间)。"""
    # 只对未裁决区间做同值兜底；显式放行只作用于原文中的这个位置。
    repeated = entries if repeated_entries is None else repeated_entries
    parts: list[str] = []
    allowed: list[tuple[int, int]] = []
    cursor = length = 0
    for e in sorted(entries, key=lambda x: x.finding.span[0]):
        start, end = e.finding.span
        gap = mask_repeated_values(text[cursor:start], repeated)
        parts.append(gap)
        length += len(gap)
        ph = _placeholder(e)
        value = text[start:end] if ph is None else ph
        if preview_spans is not None:
            preview_spans.append({"finding_id": e.finding.id, "start": length, "end": length + len(value)})
        if ph is None:
            allowed.append((length, length + len(value)))
        parts.append(value)
        length += len(value)
        cursor = end
    parts.append(mask_repeated_values(text[cursor:], repeated))
    return "".join(parts), allowed


def mask_repeated_values(text: str, entries: list[Entry]) -> str:
    # 值兜底全量替换（同一值在其他位置重复出现）
    for e in sorted(
        [x for x in entries if x.value and redactor.should_mask_value(x.value)],
        key=lambda x: -len(x.value),
    ):
        ph = _placeholder(e)
        if ph is None or e.value in ph or e.value not in text:
            continue
        sentinel = _VALUE_SENTINEL + sha256_hex(e.value)[:16] + "\x00"
        parts = redactor._PLACEHOLDER_RE.split(text)
        for i, part in enumerate(parts):
            if i % 2 == 0:
                parts[i] = part.replace(e.value, sentinel)
        text = "".join(parts).replace(sentinel, ph)
    return text


def entry_to_report(e: Entry) -> dict:
    f = e.finding
    return {
        "finding_id": f.id,
        "type": e.type,
        "name": e.name,
        "description": e.description,
        "source": e.source,
        "action": e.action,
        "rule": f.rule,
        "confidence": f.confidence,
        "detector": f.detector,
        "value_hash": e.value_hash,
        "span": list(f.span),
        "ref_id": e.ref_id,
        "private_ref": _placeholder(e) or None,
        "vault": {
            "kind": e.vault_kind,
            "name": e.vault_name,
            "field_name": e.field_name,
            "item_id": None,
            "saved": False,
        },
    }
