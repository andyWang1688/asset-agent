"""脱敏：把识别出的 Finding 替换为引用/占位符。

- 存保险柜 → [🔒 可读名称](private:REF_ID)（值只存 Vaultwarden，引用 ID 与值无可逆关系）
- 仅脱敏 → [REDACTED:rule]（原值销毁）
- 旧格式 [SECRET_REF:name] 作为兼容格式继续可读/可掩码
LLM 输出再扫描时，命中片段直接删除。
"""
import json
import re

from ..crypto import sha256_hex
from .rules import Finding, KIND_CREDENTIAL, scan_text


def ref_id_for(f: Finding, namespace: str = "") -> str:
    """稳定的私密引用 ID：由 (命名空间 + Finding.id) 派生。命名空间按来源/资料隔离，
    保证不同资料/条目间唯一；与敏感值无可逆关系；同一 Finding 生命周期内恒定。"""
    return "pr_" + sha256_hex(namespace + "\x00" + f.id)[:16]


def private_ref(name: str, ref_id: str) -> str:
    """私密引用占位符（值只在 Vaultwarden）。"""
    return f"[🔒 {name}](private:{ref_id})"


def redact_ref(rule: str) -> str:
    """仅脱敏占位符（原值销毁）。"""
    return f"[REDACTED:{rule}]"


def _ref_name(f: Finding) -> str:
    if f.key_hint:
        clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", f.key_hint).strip("-").lower()
        if clean and len(clean) <= 40:
            return clean
    return f"{f.rule}-{sha256_hex(f.value)[:8]}"


def placeholder(f: Finding, ref_name: str | None = None) -> str:
    """Finding 的脱敏占位符（仅包含引用名/规则名，绝不含值）。"""
    if ref_name:
        return private_ref(ref_name, ref_id_for(f))
    return redact_ref(f.rule)


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


# 严格占位符识别：只信任结构合法（可读名称无 "="/"]"、引用 ID 为 pr_hex、规则为安全标识）的占位符，
# 防止伪造标签把秘密塞进名称/引用而免检。
_SAFE_NAME = r"[A-Za-z0-9_\-\u4e00-\u9fff ]{1,60}"
_PRIVATE_REF_STRICT = rf"\[🔒\s*{_SAFE_NAME}\]\(private:pr_[0-9a-f]{{16}}\)"
_REDACTED_STRICT = r"\[REDACTED:[A-Za-z0-9_]{1,40}\]"
_LEGACY_SECRET_REF_STRICT = rf"\[SECRET_REF:{_SAFE_NAME}\]"
_PLACEHOLDER_RE = re.compile(
    rf"({_PRIVATE_REF_STRICT}|{_REDACTED_STRICT}|{_LEGACY_SECRET_REF_STRICT})"
)


def registered_refs(secret_refs) -> set[str]:
    """从已安全处理的来源元数据重建精确登记的私密引用占位符集合。

    secret_refs 可为 sources.secret_refs 的 JSON 字符串或已解析的 ref 列表
    （每项含 name/ref_id）。只取引用名与引用 ID，绝不读取任何秘密原文。
    """
    if isinstance(secret_refs, str):
        try:
            secret_refs = json.loads(secret_refs or "[]")
        except json.JSONDecodeError:
            secret_refs = []
    out: set[str] = set()
    for r in secret_refs or []:
        if not isinstance(r, dict):
            continue
        name, ref_id = r.get("name"), r.get("ref_id")
        if name and ref_id:
            out.add(private_ref(str(name), str(ref_id)))
    return out


def mask_placeholders(text: str, valid: set | None = None) -> str:
    """复扫前屏蔽系统生成的占位符。用等长 '#' 填充（spans/放行区间偏移保持有效）。

    valid 提供时（含空集合）只屏蔽这些精确登记的引用，绝不凭语法形状豁免其余引用；
    未提供可信集合时不作任何形状豁免，原文本直接交给扫描，伪造标签不会被免检。"""
    if valid is None:
        return text
    for ph in sorted(set(valid), key=len, reverse=True):
        text = text.replace(ph, "[" + "#" * max(0, len(ph) - 2) + "]")
    return text


_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)([^)]*)\)")


def mask_wiki_link_targets(text: str, safe_paths: set[str] | None) -> str:
    """对 Wiki/Markdown 链接的“目标位置”做等长掩码（标签/正文仍完整保留）。

    只豁免 safe_paths 中精确登记的、已程序验证为真实 Wiki 文件或本轮已验证待写页面的路径；
    未知路径、链接标签、正文一律不改。等长掩码保持偏移有效，后续检测可映射回原文，
    因此合法目的地即便配了 password=... 的敏感标签，标签部分仍会被正常检出。"""
    if not safe_paths:
        return text

    def _masked(target: str) -> str:
        return "#" * len(target)

    def _wiki(m: re.Match) -> str:
        target = m.group(1)
        if target.strip() not in safe_paths:
            return m.group(0)
        label = m.group(2)
        return "[[" + _masked(target) + (f"|{label}" if label is not None else "") + "]]"

    def _md(m: re.Match) -> str:
        target = m.group(2)
        if target not in safe_paths:
            return m.group(0)
        return "[" + m.group(1) + "](" + _masked(target) + m.group(3) + ")"

    text = _WIKI_LINK_RE.sub(_wiki, text)
    return _MD_LINK_RE.sub(_md, text)


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


def sanitize_llm_output(text: str, policy: dict | None = None,
                        valid: set | None = None,
                        safe_wiki_paths: set | None = None) -> tuple[str, list[str]]:
    """扫描 LLM 输出；命中片段删除并返回命中规则名，用于安全事件记录。

    valid 提供时（含空集合）只屏蔽精确登记的私密引用；未提供时不作任何形状豁免，
    引用名与普通正文完整执行安全检测。
    safe_wiki_paths 提供时只对链接目标位置的已验证路径做掩码；标签/正文仍扫描。"""
    masked = mask_placeholders(text, valid)
    masked = mask_wiki_link_targets(masked, safe_wiki_paths)
    findings = scan_text(masked, policy)
    out = text
    for f in sorted(findings, key=lambda x: -x.span[0]):
        out = out[: f.span[0]] + "［已删除疑似秘密片段］" + out[f.span[1] :]
    return out, [f.rule for f in findings]
