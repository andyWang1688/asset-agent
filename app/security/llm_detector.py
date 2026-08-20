"""可选 security 增强检测器：接入 ScanEngine 本地检测（Regex → Context → Entropy）之后。

约束（fail-closed）：
- critical=False：任何失败（网络/超时/JSON/非法输出）都由 ScanEngine.scan_async 捕获并
  回退本地检测结果，绝不阻断基础检测、绝不上抛。
- 端点：security 模型仅允许 localhost/内网本地端点（provider 层强制，禁止公网调用、
  无放开开关），本地漏检的原文只可能发往本机/内网部署的模型，绝不发往公网模型。
- 发送给模型的输入先经等长掩码脱敏（redactor.mask_for_security_model），
  已知秘密原文绝不离开本机。
- 模型输出只用于「新增或加严」：kind 白名单、span 边界校验、置信度钳制，
  与本地结果经 merge_findings 合并（每组只取最高类别/最高置信度，永不降级、永不删除）。
- 响应先经本地再扫描脱敏，防止模型回显秘密。
"""
import json

from ..llm.provider import LLMProvider
from . import redactor
from .rules import KIND_UNKNOWN, KINDS, Finding

MAX_FINDINGS = 50
MAX_EVIDENCE_CHARS = 120

SYSTEM_PROMPT = (
    "你是敏感信息检测助手，运行在本地安全扫描管线中。输入文本中的已知敏感片段已被等长掩码为 #，"
    "你的任务是找出本地检测可能遗漏的敏感信息（凭证、个人信息、高熵疑似值）。"
    "只输出严格 JSON：{\"findings\":[{\"span\":[开始偏移,结束偏移],\"kind\":\"credential|pii|unknown_suspect\","
    "\"confidence\":0.0到1.0,\"evidence\":\"简短理由（不得包含任何敏感值原文）\"}]}。"
    "偏移按字符计数，起点为 0，必须落在文本范围内；没有发现就输出 {\"findings\":[]}。"
    "不要在 evidence 或任何字段中复述敏感值原文。"
)


class SecurityDetectorError(Exception):
    """security 模型输出不可用（可选层：由调用方回退本地检测结果）。"""


def _parse_findings_json(resp: str) -> dict:
    text = (resp or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1 and text[:nl].strip().lower() in ("json",):
            text = text[nl + 1 :]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1:
            raise SecurityDetectorError("security 模型输出不是 JSON")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise SecurityDetectorError("security 模型输出 JSON 无法解析") from e
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise SecurityDetectorError("security 模型输出缺少 findings 列表")
    return data


class SecurityModelDetector:
    """LLM 增强检测层：只能新增或加严 Finding；失败时调用方回退本地检测结果。"""

    name = "security_llm"
    critical = False

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def build_prompt(self, masked_text: str) -> str:
        return "【安全增强检测】\n<待检文本>\n" + masked_text + "\n</待检文本>"

    async def detect(self, text: str, ctx, existing: list[Finding] | None = None,
                     on_warning=None) -> list[Finding]:
        existing = existing or []
        masked = redactor.mask_for_security_model(text, existing)
        resp = await self.provider.complete(
            SYSTEM_PROMPT, self.build_prompt(masked), json_mode=True, max_tokens=2000
        )
        # 防御：响应先经本地再扫描，模型回显的秘密片段直接删除（残留会导致 JSON 解析失败 → 回退）
        clean, hits = redactor.sanitize_llm_output(resp)
        if hits:
            from .. import db

            db.log_security("llm_output_secret", f"security 增强模型响应命中规则 {hits}，片段已删除")
        data = _parse_findings_json(clean)
        out: list[Finding] = []
        for item in data["findings"][:MAX_FINDINGS]:
            f = self._to_finding(item, text, existing)
            if f is not None:
                out.append(f)
        return out

    def _to_finding(self, item, text: str, existing: list[Finding]) -> Finding | None:
        if not isinstance(item, dict):
            return None
        span = item.get("span")
        if not (isinstance(span, list) and len(span) == 2
                and isinstance(span[0], int) and isinstance(span[1], int)
                and not isinstance(span[0], bool) and not isinstance(span[1], bool)):
            return None
        s, e = span
        if not (0 <= s < e <= len(text)):
            return None
        value = text[s:e]
        if not value.strip() or "#" in value:
            return None
        kind = item.get("kind") if item.get("kind") in KINDS else KIND_UNKNOWN
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(1.0, max(0.1, confidence))
        reason = str(item.get("evidence") or "").strip()[:MAX_EVIDENCE_CHARS]
        for v in {f.value for f in existing} | {value}:
            if v and len(v) >= 4 and v in reason:
                reason = reason.replace(v, "…")
        evidence = f"安全增强模型命中（{reason}）" if reason else "安全增强模型命中"
        return Finding(
            id=f"{self.name}:llm_security:{s}:{e}",
            kind=kind,
            rule="llm_security",
            span=(s, e),
            confidence=confidence,
            evidence=evidence,
            suggested_action="redact",
            detector=self.name,
            value=value,
            key_hint=None,
        )
