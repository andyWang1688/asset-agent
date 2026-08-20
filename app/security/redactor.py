"""脱敏：把识别出的 Finding 替换为引用/占位符。

- credential → [SECRET_REF:name]（存入 Vaultwarden 的引用）
- pii / unknown_suspect → [REDACTED:rule]（仅脱敏，不存凭证库）
- 相同值只生成一个凭证引用；refs 只保留哈希，不保留秘密原文。
LLM 输出再扫描时，命中片段直接删除。
"""
import re

from ..crypto import sha256_hex
from .rules import Finding, KIND_CREDENTIAL, scan_text


def _ref_name(f: Finding) -> str:
    if f.key_hint:
        clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", f.key_hint).strip("-").lower()
        if clean and len(clean) <= 40:
            return clean
    return f"{f.rule}-{sha256_hex(f.value)[:8]}"


def placeholder(f: Finding, ref_name: str | None = None) -> str:
    """Finding 的脱敏占位符（仅包含规则名/引用名，绝不含值）。"""
    if f.kind == KIND_CREDENTIAL and ref_name:
        return f"[SECRET_REF:{ref_name}]"
    return f"[REDACTED:{f.rule}]"


def _dedupe_names(findings: list[Finding]) -> dict[str, str]:
    """按值去重并生成唯一引用名。"""
    by_value: dict[str, Finding] = {}
    for f in findings:
        by_value.setdefault(f.value, f)
    names: dict[str, str] = {}
    used: dict[str, int] = {}
    for value, f in by_value.items():
        name = _ref_name(f)
        n = used.get(name, 0)
        if n:
            name = f"{name}-{n + 1}"
        used.setdefault(name, 0)
        used[name] += 1
        names[value] = name
    return names


def ref_names(findings: list[Finding]) -> dict[str, str]:
    """按值去重生成引用名（value → ref_name）。"""
    return _dedupe_names(findings)


def should_mask_value(value: str) -> bool:
    """兜底掩码/替换阈值（预览与确认视图共用）：
    >=8 全量；4~7 字符仅当含符号或高熵（Shannon>=2.5），避免误伤普通短词。"""
    if len(value) >= 8:
        return True
    if len(value) >= 4:
        if any(not ch.isalnum() for ch in value):
            return True
        from .detectors import shannon_entropy

        return shannon_entropy(value) >= 2.5
    return False


_PLACEHOLDER_RE = re.compile(r"\[(?:SECRET_REF|REDACTED):[^\]]+\]")


def mask_placeholders(text: str) -> str:
    """复扫前屏蔽系统生成的占位符（占位符不是数据，避免引用名被误判）。
    用等长的 '#' 填充：长度不变，spans/放行区间偏移保持有效；'#' 不构成任何 token。"""
    return _PLACEHOLDER_RE.sub(lambda m: "[" + "#" * (len(m.group(0)) - 2) + "]", text)


def mask_for_security_model(text: str, findings: list[Finding]) -> str:
    """security 增强模型的输入脱敏：等长掩码已知 Finding（span 及全文重复值），
    偏移保持不变，模型返回的 span 可直接映射回原文。
    任何已识别片段（含值兜底）都不会离开本机，公网模型也绝不接收未脱敏输入。"""
    masked = text
    for f in sorted(findings, key=lambda x: -x.span[0]):
        if 0 <= f.span[0] < f.span[1] <= len(masked):
            masked = masked[: f.span[0]] + "#" * (f.span[1] - f.span[0]) + masked[f.span[1]:]
    for f in sorted(findings, key=lambda x: -len(x.value or "")):
        v = f.value or ""
        if v and "#" not in v and should_mask_value(v):
            masked = masked.replace(v, "#" * len(v))
    return masked


def build_refs(text: str, policy: dict | None = None) -> tuple[str, list[dict]]:
    """返回 (脱敏文本, [{name,value,kind,rule,value_hash}])。
    credential 用 [SECRET_REF:name]，pii/疑似用 [REDACTED:rule]。相同值只生成一个凭证引用。"""
    findings = scan_text(text, policy)
    names = _dedupe_names(findings)
    by_value: dict[str, Finding] = {}
    for f in findings:
        by_value.setdefault(f.value, f)

    refs = []
    for value, f in by_value.items():
        if f.kind != KIND_CREDENTIAL:
            continue
        refs.append(
            {
                "name": names[value],
                "value": value,
                "kind": f.kind,
                "rule": f.rule,
                "value_hash": sha256_hex(value)[:16],
            }
        )

    sanitized = text
    for f in sorted(findings, key=lambda x: -x.span[0]):
        sanitized = (
            sanitized[: f.span[0]]
            + placeholder(f, names.get(f.value) if f.kind == KIND_CREDENTIAL else None)
            + sanitized[f.span[1] :]
        )
    # 兜底：同一值在别处再次出现（未命中规则）也替换，长度阈值避免误伤短词
    for v in by_value:
        if len(v) >= 8:
            name = names[v]
            ref = placeholder(by_value[v], name if by_value[v].kind == KIND_CREDENTIAL else None)
            sanitized = sanitized.replace(v, ref)
    return sanitized, refs


def sanitize_llm_output(text: str, policy: dict | None = None) -> tuple[str, list[str]]:
    """扫描 LLM 输出；命中片段删除并返回命中规则名，用于安全事件记录。"""
    findings = scan_text(text, policy)
    out = text
    for f in sorted(findings, key=lambda x: -x.span[0]):
        out = out[: f.span[0]] + "［已删除疑似秘密片段］" + out[f.span[1] :]
    return out, [f.rule for f in findings]
