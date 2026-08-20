"""Detector 接口与检测管线：正则规则 → 上下文 → 熵值，合并去重。

约束：
- 后层只能新增或加严（合并只取每个重叠组内最高类别/最高置信度，永不降级、永不删除）。
- 熵值不得单独把短字符串判为凭证；须结合长度、字符结构和上下文，疑似项归 unknown_suspect。
- 基础检测器失败：阻断（DetectorError 上抛）；可选检测器失败：回退基础结果（本批无增强检测，
  但接口通过 critical 标记预留该能力）。
"""
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .policy import default_policy
from .rules import (
    Finding,
    KIND_CREDENTIAL,
    KIND_PII,
    KIND_UNKNOWN,
    RULES,
    VALIDATORS,
    canonical_kind,
)


class DetectorError(Exception):
    """检测器执行失败（基础检测器失败必须阻断）。"""


@dataclass
class ScanContext:
    text: str
    policy: dict
    keyword_positions: list[int]


class Detector(Protocol):
    name: str
    critical: bool

    def detect(self, text: str, ctx: ScanContext) -> list[Finding]: ...


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    counts = Counter(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def char_classes(s: str) -> int:
    return sum(
        [
            any(ch.isdigit() for ch in s),
            any(ch.isupper() for ch in s),
            any(ch.islower() for ch in s),
            any(not ch.isalnum() for ch in s),
        ]
    )


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PURE_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")


def _is_uuid_or_hash(token: str) -> bool:
    return bool(_UUID_RE.match(token) or _PURE_HEX_RE.match(token))


def _default_confidence(kind: str, validator) -> float:
    if kind == KIND_CREDENTIAL:
        return 0.9 if validator else 0.8
    if kind == KIND_PII:
        return 0.85
    return 0.5


_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]")


def keyword_positions(text: str, keywords: list[str]) -> list[int]:
    return [p for p, _ in keyword_hits(text, keywords)]


def keyword_hits(text: str, keywords: list[str]) -> list[tuple[int, str]]:
    """返回 (关键词起始位置, 关键词) 列表（按位置排序）。
    ASCII 关键词按词边界匹配（避免命中前一个秘密值内部的子串，如 Sup3rSecret! 里的 secret）。"""
    lower = text.lower()
    hits: list[tuple[int, str]] = []
    for kw in keywords:
        if _ASCII_WORD_RE.search(kw):
            pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(kw.lower()) + r"(?![A-Za-z0-9_])")
            for m in pattern.finditer(lower):
                hits.append((m.start(), kw))
        else:
            start = 0
            needle = kw.lower()
            while True:
                i = lower.find(needle, start)
                if i == -1:
                    break
                hits.append((i, kw))
                start = i + 1
    return sorted(hits, key=lambda x: x[0])


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


_SEVERITY = {KIND_CREDENTIAL: 3, KIND_PII: 2, KIND_UNKNOWN: 1}


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """按重叠 span 分组合并：每组保留最高类别；同类别取最高置信度。
    只可能新增或加严：任何单条 finding 的类别/置信度都不会被降低。"""
    items = sorted(
        findings, key=lambda f: (f.span[0], -(f.span[1] - f.span[0]), _SEVERITY.get(f.kind, 0))
    )
    groups: list[list[Finding]] = []
    for f in items:
        placed = False
        for g in groups:
            if any(overlaps(f.span, x.span) for x in g):
                g.append(f)
                placed = True
                break
        if not placed:
            groups.append([f])
    out: list[Finding] = []
    for g in groups:
        top_sev = max(_SEVERITY.get(f.kind, 0) for f in g)
        candidates = [f for f in g if _SEVERITY.get(f.kind, 0) == top_sev]
        winner = max(candidates, key=lambda f: f.confidence)
        conf = max(f.confidence for f in candidates)
        segs: list[str] = []
        for f in g:
            for seg in f.evidence.split("；"):
                if seg and seg not in segs:
                    segs.append(seg)
        out.append(replace(winner, confidence=conf, evidence="；".join(segs)))
    return sorted(out, key=lambda f: f.span[0])


def _policy_get(policy: dict, path: str, default=None):
    node = policy
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node if node is not None else default


@dataclass(frozen=True)
class RuleSpec:
    name: str
    pattern: str
    kind: str
    validator: Callable[[str], bool] | None
    confidence: float
    extra: bool = False


def build_rules(policy: dict) -> list[RuleSpec]:
    specs: list[RuleSpec] = []
    disabled = set(_policy_get(policy, "detection.builtin_rules.disabled", []) or [])
    for name, pattern, kind, *rest in RULES:
        if name in disabled:
            continue
        validator = rest[0] if rest else None
        ckind = canonical_kind(kind)
        specs.append(RuleSpec(name, pattern, ckind, validator, _default_confidence(ckind, validator)))
    for ex in _policy_get(policy, "detection.extra_rules", []) or []:
        validator = VALIDATORS.get(ex.get("validator")) if ex.get("validator") else None
        specs.append(
            RuleSpec(ex["name"], ex["pattern"], ex["kind"], validator, float(ex.get("confidence", 0.9)), extra=True)
        )
    return specs


_TRIM = ".,;:!?)]}》】\"'`"
_TRIM_KV = ",;，；\"'` "


class RegexRulesDetector:
    """内置 + 策略自定义正则规则。自定义规则执行失败视为可选增强：跳过并回调告警。"""

    name = "regex"
    critical = True

    def detect(self, text: str, ctx: ScanContext, on_warning=None) -> list[Finding]:
        findings: list[Finding] = []
        covered: list[tuple[int, int]] = []
        for spec in build_rules(ctx.policy):
            try:
                matches = _matches(spec, text, ctx.policy)
            except (DetectorError, re.error) as e:
                if spec.extra:
                    if on_warning:
                        on_warning(f"自定义规则 {spec.name} 执行失败已跳过: {e}")
                    continue
                raise DetectorError(f"基础规则 {spec.name} 执行失败") from e
            for m in matches:
                value = m.group("value") if spec.name == "key_value_secret" else m.group(0)
                trim = _TRIM_KV if spec.name == "key_value_secret" else _TRIM
                value = value.strip().strip("'\" ").rstrip(trim)
                if len(value) < 4:
                    continue
                if spec.validator and not spec.validator(value):
                    continue
                if any(s <= m.start() < e for s, e in covered):
                    continue
                findings.append(
                    Finding(
                        id=f"{self.name}:{spec.name}:{m.start()}:{m.end()}",
                        kind=spec.kind,
                        rule=spec.name,
                        span=(m.start(), m.end()),
                        confidence=spec.confidence,
                        evidence=f"规则 {spec.name} 命中",
                        suggested_action="redact",
                        detector=self.name,
                        value=value,
                        key_hint=(m.groupdict().get("key") if spec.name == "key_value_secret" else None),
                    )
                )
                if spec.name == "private_key_block":
                    covered.append((m.start(), m.end()))
        return findings


def _matches(spec: RuleSpec, text: str, policy: dict) -> list:
    compiled = re.compile(spec.pattern)
    if not spec.extra:
        return list(compiled.finditer(text))
    if len(text) > int(_policy_get(policy, "detection.extra_max_input_chars", 200_000)):
        raise DetectorError(f"输入超过自定义规则长度上限（{len(text)} 字符）")
    timeout = float(_policy_get(policy, "detection.extra_exec_timeout_seconds", 2.0))
    # 自定义规则用 regex 模块原生 timeout 执行（CPython re 无超时且灾难性回溯不释放 GIL）
    import regex

    try:
        return list(regex.compile(spec.pattern).finditer(text, timeout=timeout))
    except TimeoutError as e:
        raise DetectorError("自定义规则执行超时") from e


class ContextDetector:
    """上下文信号：关键词附近的已有 Finding 提高置信度；关键词后的高熵值补报。"""

    name = "context"
    critical = True

    def detect(self, text: str, ctx: ScanContext, existing: list[Finding] | None = None) -> list[Finding]:
        cfg = _policy_get(ctx.policy, "detection.context") or {}
        if not cfg.get("enabled", True):
            return []
        window = int(cfg.get("window", 40))
        boost = float(cfg.get("boost", 0.15))
        keywords = [str(k) for k in (cfg.get("keywords") or [])]
        if not keywords:
            return []

        existing = existing or []
        out: list[Finding] = []

        # 1) 已有 Finding 附近出现关键词 → 提高置信度（加严，不新增）。
        #    证据只记录关键词本身（白名单词），绝不包含上下文文本/秘密值。
        hits = keyword_hits(text, keywords)
        for f in existing:
            for p, kw in hits:
                if 0 <= f.span[0] - p <= window and f.confidence < 0.98:
                    out.append(
                        replace(
                            f,
                            confidence=min(0.98, f.confidence + boost),
                            evidence=f"{f.evidence}；上下文命中关键词“{kw}”",
                        )
                    )
                    break

        # 2) 关键词后的孤立高熵值（正则漏网）→ 凭证或疑似
        token_re = re.compile(r"[A-Za-z0-9_\-+/=.]{8,}")
        for p, kw in keyword_hits(text, keywords):
            after = text[p + len(kw) : p + len(kw) + window]
            m = re.match(r"^[\s:='\"]{0,4}(?P<tok>[A-Za-z0-9_\-+/=.]{8,})", after)
            if not m:
                continue
            tok = m.group("tok")
            tok_start = p + len(kw) + m.start("tok")
            span = (tok_start, tok_start + len(tok))
            if len(tok) < 8 or char_classes(tok) < 2:
                continue
            if any(overlaps(span, f.span) for f in existing) or any(overlaps(span, f.span) for f in out):
                continue
            ent = shannon_entropy(tok)
            if ent < 2.5:
                continue
            if len(tok) >= 12 and char_classes(tok) >= 3 and ent >= 3.0:
                kind, rule, conf = KIND_CREDENTIAL, "context_keyword_value", 0.7
            else:
                kind, rule, conf = KIND_UNKNOWN, "context_suspect_value", 0.55
            out.append(
                Finding(
                    id=f"{self.name}:{rule}:{span[0]}:{span[1]}",
                    kind=kind,
                    rule=rule,
                    span=span,
                    confidence=conf,
                    evidence=f"关键词“{kw}”附近的疑似值（熵 {ent:.2f}）",
                    suggested_action="redact",
                    detector=self.name,
                    value=tok,
                    key_hint=kw,
                )
            )
        return out


class EntropyDetector:
    """Shannon 熵信号：长且字符结构复杂的高熵 token 才进入疑似项（unknown_suspect）；
    位于上下文关键词附近且结构充分时才升级为凭证。短字符串绝不单独判为凭证。"""

    name = "entropy"
    critical = True

    def detect(self, text: str, ctx: ScanContext, existing: list[Finding] | None = None) -> list[Finding]:
        cfg = _policy_get(ctx.policy, "detection.entropy") or {}
        if not cfg.get("enabled", True):
            return []
        min_length = int(cfg.get("min_length", 16))
        min_shannon = float(cfg.get("min_shannon", 3.5))
        max_findings = int(cfg.get("max_findings", 50))
        ctx_min_length = int(cfg.get("context_min_length", 12))
        window = int(_policy_get(ctx.policy, "detection.context.window", 40))
        boost = float(_policy_get(ctx.policy, "detection.context.boost", 0.15))
        positions = ctx.keyword_positions or []

        token_re = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-+/=]{%d,}" % (min_length - 1))
        existing = existing or []
        findings: list[Finding] = []
        for m in token_re.finditer(text):
            if len(findings) >= max_findings:
                break
            tok = m.group(0)
            if _is_uuid_or_hash(tok):
                continue
            span = (m.start(), m.end())
            if any(overlaps(span, f.span) for f in existing):
                continue
            ent = shannon_entropy(tok)
            if ent < min_shannon:
                continue
            if char_classes(tok) < 2:
                continue
            near = any(0 < m.start() - p <= window for p in positions)
            if near and len(tok) >= ctx_min_length and char_classes(tok) >= 3:
                kind, rule = KIND_CREDENTIAL, "entropy_context"
                conf = min(0.65, 0.5 + boost)
            else:
                kind, rule = KIND_UNKNOWN, "entropy_token"
                conf = 0.5
            findings.append(
                Finding(
                    id=f"{self.name}:{rule}:{m.start()}:{m.end()}",
                    kind=kind,
                    rule=rule,
                    span=span,
                    confidence=conf,
                    evidence=f"Shannon 熵 {ent:.2f}，长度 {len(tok)}，字符类 {char_classes(tok)}"
                    + ("，且位于上下文关键词附近" if near else ""),
                    suggested_action="redact",
                    detector=self.name,
                    value=tok,
                    key_hint=None,
                )
            )
        return findings


class ScanEngine:
    """检测管线：正则 → 上下文 → 熵值 → （可选）security 增强模型；逐层合并。
    返回统一 Finding（含 id 与建议动作）。scan() 为纯本地管线（同步上下文可用）；
    scan_async() 在本地检测之后追加 security 增强层（可选，失败回退本地结果）。"""

    def __init__(self, policy: dict | None = None, on_warning: Callable[[str], None] | None = None,
                 security_provider: "object | None" = None) -> None:
        from .policy import _deep_merge

        self.policy = _deep_merge(default_policy(), policy or {})
        self.on_warning = on_warning
        self.security_provider = security_provider

    def _make_ctx(self, text: str) -> ScanContext:
        keywords = [str(k) for k in (_policy_get(self.policy, "detection.context.keywords") or [])]
        return ScanContext(text=text, policy=self.policy, keyword_positions=keyword_positions(text, keywords))

    def scan(self, text: str) -> list[Finding]:
        ctx = self._make_ctx(text)

        # 基础层：正则规则。失败即阻断（不落盘、不进云端）。
        regex_det = RegexRulesDetector()
        merged = merge_findings(regex_det.detect(text, ctx, on_warning=self.on_warning))

        # 上下文层
        context_det = ContextDetector()
        try:
            ctx_findings = context_det.detect(text, ctx, existing=merged)
        except DetectorError:
            if context_det.critical:
                raise
            ctx_findings = []
        merged = merge_findings(merged + ctx_findings)

        # 熵值层
        entropy_det = EntropyDetector()
        try:
            ent_findings = entropy_det.detect(text, ctx, existing=merged)
        except DetectorError:
            if entropy_det.critical:
                raise
            ent_findings = []
        merged = merge_findings(merged + ent_findings)

        return self._apply_defaults(merged)

    async def scan_async(self, text: str) -> list[Finding]:
        """本地检测 + 可选 security 增强层。增强层失败（网络/超时/非法输出）时
        记安全事件并回退本地检测结果——绝不阻断、绝不降低基础检测。"""
        merged = self.scan(text)
        if self.security_provider is None:
            return merged
        from .llm_detector import SecurityModelDetector  # 局部导入避免循环依赖

        det = SecurityModelDetector(self.security_provider)
        try:
            extra = await det.detect(text, self._make_ctx(text), existing=merged,
                                     on_warning=self.on_warning)
        except Exception as e:
            from .. import db

            try:
                db.log_security(
                    "security_model_fallback",
                    f"security 增强检测失败，已回退本地检测结果: {type(e).__name__}: {str(e)[:200]}",
                )
            except Exception:
                pass
            if self.on_warning:
                self.on_warning(f"security 增强检测失败已回退: {type(e).__name__}")
            return merged
        # 合并只可能新增或加严（每组取最高类别/最高置信度），本地结果永不被删除或降级
        return self._apply_defaults(merge_findings(merged + extra))

    def _apply_defaults(self, findings: list[Finding]) -> list[Finding]:
        defaults = _policy_get(self.policy, "actions.defaults") or {}
        out: list[Finding] = []
        for f in findings:
            out.append(replace(f, suggested_action=defaults.get(f.kind, "redact")))
        return sorted(out, key=lambda f: f.span[0])
