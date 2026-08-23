"""安全策略：config/policy.yaml 的默认值、校验、原子读写。

约束：
- 设置服务读写；Wiki 编译模型只读（以系统提示词片段注入，见 wiki/compiler）。
- YAML 只能 safe_load，禁止任意代码/标签；validator 只能引用内置白名单。
- 策略与审计记录不得包含密码、Token、API Key 等秘密原文。
- 非法策略返回表单错误（字段路径列表），不影响服务：服务继续使用上一次有效策略。
"""
import os
import re
import threading
from copy import deepcopy
from pathlib import Path

import regex
import yaml

from .rules import (
    ACTION_ALLOW,
    ACTION_REDACT,
    ACTION_STORE,
    BUILTIN_RULE_NAMES,
    KIND_CREDENTIAL,
    KIND_PII,
    KIND_UNKNOWN,
    KINDS,
    VALIDATORS,
)

POLICY_VERSION = 1

DEFAULT_POLICY: dict = {
    "version": POLICY_VERSION,
    "gate": {
        # on_findings：发现 Finding 时进入确认；always：始终确认；never：跳过闸门
        "confirm_before_llm": "on_findings",
    },
    "detection": {
        "context": {
            "enabled": True,
            "window": 40,
            "boost": 0.15,
            "keywords": [
                "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
                "access_key", "client_secret", "authorization", "bearer",
                "密码", "口令", "密钥", "令牌", "私钥", "凭据",
            ],
        },
        "entropy": {
            "enabled": True,
            "min_length": 16,
            "min_shannon": 3.5,
            "max_findings": 50,
            "context_min_length": 12,
        },
        "builtin_rules": {"disabled": []},
        "extra_rules": [],
        # 自定义正则的运行时护栏：输入长度上限 / 单规则执行超时（秒）/ 最大规则数
        "extra_max_input_chars": 200_000,
        "extra_exec_timeout_seconds": 2.0,
    },
    "actions": {
        "defaults": {
            KIND_CREDENTIAL: ACTION_STORE,
            KIND_PII: ACTION_REDACT,
            KIND_UNKNOWN: ACTION_REDACT,
        }
    },
}

# 各类别在确认页允许的裁决动作（PII 仅脱敏，不允许存凭证库）
KIND_ALLOWED_ACTIONS = {
    KIND_CREDENTIAL: (ACTION_STORE, ACTION_REDACT, ACTION_ALLOW),
    KIND_PII: (ACTION_REDACT, ACTION_ALLOW),
    KIND_UNKNOWN: (ACTION_REDACT, ACTION_ALLOW),
}

GATE_MODES = ("on_findings", "always", "never")
_EXTRA_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_EXTRA_RULES = 20
MAX_PATTERN_CHARS = 300
MAX_KEYWORDS = 60
MAX_KEYWORD_CHARS = 40


class PolicyError(ValueError):
    """策略非法（携带字段路径，用于表单错误）。"""


def _deep_merge(base: dict, patch: dict) -> dict:
    out = deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def default_policy() -> dict:
    return deepcopy(DEFAULT_POLICY)


def _plain_type_check(data, path: str, errors: list[str]) -> None:
    """递归确认 YAML 只包含基础类型（safe_load 之外的双保险，禁止对象/代码）。"""
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str):
                errors.append(f"{path}: 键必须为字符串")
            _plain_type_check(v, f"{path}.{k}" if path else k, errors)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _plain_type_check(v, f"{path}[{i}]", errors)
    elif not isinstance(data, (str, int, float, bool)) and data is not None:
        errors.append(f"{path}: 不支持的 YAML 类型 {type(data).__name__}")


def _run_regex_with_timeout(pattern: "regex.Pattern", text: str, timeout: float) -> list:
    """使用 regex 模块原生 timeout 执行（CPython re 无超时且灾难性回溯时不释放 GIL）。"""
    return list(pattern.finditer(text, timeout=timeout))


def validate_policy(data: object) -> dict:
    """校验并归一化策略；非法时抛 PolicyError（消息含字段路径）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise PolicyError("policy: 必须是 YAML 映射")
    _plain_type_check(data, "", errors)
    if errors:
        raise PolicyError("；".join(errors))

    merged = _deep_merge(DEFAULT_POLICY, data)
    gate = merged["gate"]
    if not isinstance(gate, dict) or gate.get("confirm_before_llm") not in GATE_MODES:
        raise PolicyError(f"gate.confirm_before_llm: 必须是 {GATE_MODES} 之一")

    detection = merged["detection"]
    ctx = detection["context"]
    if not isinstance(ctx.get("enabled"), bool):
        raise PolicyError("detection.context.enabled: 必须是布尔值")
    window = ctx.get("window")
    if not isinstance(window, int) or not 0 <= window <= 500:
        raise PolicyError("detection.context.window: 必须是 0..500 的整数")
    boost = ctx.get("boost")
    if not isinstance(boost, (int, float)) or not 0 <= boost <= 0.5:
        raise PolicyError("detection.context.boost: 必须是 0..0.5 的数字")
    keywords = ctx.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        raise PolicyError("detection.context.keywords: 必须是非空列表")
    if len(keywords) > MAX_KEYWORDS:
        raise PolicyError(f"detection.context.keywords: 最多 {MAX_KEYWORDS} 个关键词")
    for i, kw in enumerate(keywords):
        if not isinstance(kw, str) or not kw.strip() or len(kw) > MAX_KEYWORD_CHARS:
            raise PolicyError(f"detection.context.keywords[{i}]: 非法关键词")

    ent = detection["entropy"]
    if not isinstance(ent.get("enabled"), bool):
        raise PolicyError("detection.entropy.enabled: 必须是布尔值")
    min_len = ent.get("min_length")
    if not isinstance(min_len, int) or not 8 <= min_len <= 256:
        raise PolicyError("detection.entropy.min_length: 必须是 8..256 的整数")
    min_shannon = ent.get("min_shannon")
    if not isinstance(min_shannon, (int, float)) or not 0 <= min_shannon <= 6:
        raise PolicyError("detection.entropy.min_shannon: 必须是 0..6 的数字")
    max_find = ent.get("max_findings")
    if not isinstance(max_find, int) or not 1 <= max_find <= 500:
        raise PolicyError("detection.entropy.max_findings: 必须是 1..500 的整数")
    ctx_min = ent.get("context_min_length")
    if not isinstance(ctx_min, int) or not 8 <= ctx_min <= min_len:
        raise PolicyError(f"detection.entropy.context_min_length: 必须是 8..{min_len} 的整数")

    disabled = detection["builtin_rules"].get("disabled")
    if not isinstance(disabled, list):
        raise PolicyError("detection.builtin_rules.disabled: 必须是列表")
    for name in disabled:
        if name not in BUILTIN_RULE_NAMES:
            raise PolicyError(f"detection.builtin_rules.disabled: 未知内置规则 {name}")

    extra = detection.get("extra_rules")
    if not isinstance(extra, list):
        raise PolicyError("detection.extra_rules: 必须是列表")
    if len(extra) > MAX_EXTRA_RULES:
        raise PolicyError(f"detection.extra_rules: 最多 {MAX_EXTRA_RULES} 条")
    probe_text = ("sample line\n" * 200) + "key=value, 1234567890\n" + "a" * 5000 + "b"
    for i, rule in enumerate(extra):
        p = f"detection.extra_rules[{i}]"
        if not isinstance(rule, dict):
            raise PolicyError(f"{p}: 必须是映射")
        name = rule.get("name")
        if not isinstance(name, str) or not _EXTRA_NAME_RE.match(name):
            raise PolicyError(f"{p}.name: 必须是 1..40 位小写字母/数字/下划线")
        pattern_s = rule.get("pattern")
        if not isinstance(pattern_s, str) or not pattern_s:
            raise PolicyError(f"{p}.pattern: 不能为空")
        if len(pattern_s) > MAX_PATTERN_CHARS:
            raise PolicyError(f"{p}.pattern: 长度不得超过 {MAX_PATTERN_CHARS}")
        if rule.get("kind") not in KINDS:
            raise PolicyError(f"{p}.kind: 必须是 {KINDS} 之一")
        conf = rule.get("confidence", 0.9)
        if not isinstance(conf, (int, float)) or not 0.1 <= conf <= 1.0:
            raise PolicyError(f"{p}.confidence: 必须是 0.1..1.0 的数字")
        validator = rule.get("validator")
        if validator is not None and validator not in VALIDATORS:
            raise PolicyError(f"{p}.validator: 只能使用内置白名单 {sorted(VALIDATORS)}")
        try:
            compiled = regex.compile(pattern_s)
        except regex.error as e:
            raise PolicyError(f"{p}.pattern: 非法正则: {e}") from e
        if compiled.match(""):
            raise PolicyError(f"{p}.pattern: 不允许匹配空串")
        try:
            _run_regex_with_timeout(compiled, probe_text, timeout=1.0)
        except TimeoutError:
            raise PolicyError(f"{p}.pattern: 正则执行超时（疑似灾难性回溯）")
        except Exception as e:
            raise PolicyError(f"{p}.pattern: 正则执行异常: {type(e).__name__}") from e

    defaults = merged["actions"].get("defaults")
    if not isinstance(defaults, dict):
        raise PolicyError("actions.defaults: 必须是映射")
    for kind, action in defaults.items():
        if kind not in KINDS:
            raise PolicyError(f"actions.defaults.{kind}: 未知类别")
        if action not in KIND_ALLOWED_ACTIONS[kind]:
            raise PolicyError(f"actions.defaults.{kind}: 只允许 {KIND_ALLOWED_ACTIONS[kind]}")
    # PII 仅脱敏：默认动作强制 redact
    if defaults.get(KIND_PII) != ACTION_REDACT:
        raise PolicyError("actions.defaults.pii: 必须是 redact（PII 仅脱敏）")

    merged["version"] = POLICY_VERSION
    return merged


def mask_config_values(raw_yaml: str) -> str:
    """扫描前屏蔽配置字段值（pattern/name 及列表项关键词等）：这些是配置数据而非秘密。"""
    s = re.sub(r"(?im)^(\s*pattern\s*:\s*).*$", r'\g<1>"***"', raw_yaml)
    s = re.sub(r"(?im)^(\s*name\s*:\s*).*$", r'\g<1>"***"', s)
    s = re.sub(r"(?im)^(\s*-\s*)\S.*$", r'\g<1>"***"', s)
    return s


def policy_contains_secrets(raw_yaml: str) -> list[str]:
    """策略文本自身不得包含秘密。返回命中的规则名列表。
    使用内置全规则集（不受被扫描策略自身禁用配置影响）+ 熵检测（拦截裸高熵 Token）。"""
    from .detectors import EntropyDetector, RegexRulesDetector, ScanContext, keyword_positions

    text = mask_config_values(raw_yaml)
    ctx = ScanContext(text=text, policy=default_policy(), keyword_positions=keyword_positions(text, []))
    regex_det = RegexRulesDetector()
    findings = regex_det.detect(text, ctx)
    ent_det = EntropyDetector()
    findings = findings + ent_det.detect(text, ctx, existing=findings)
    return sorted({f.rule for f in findings})


class PolicyStore:
    """策略文件读写。路径默认 <DATA_DIR>/config/policy.yaml（可用 POLICY_FILE 覆盖）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cache: dict | None = None

    def load(self) -> dict:
        """返回当前生效策略；文件缺失/损坏时回退默认值（不影响服务）。"""
        with self._lock:
            if self._cache is not None:
                return deepcopy(self._cache)
        policy = default_policy()
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                policy = validate_policy(data if data is not None else {})
            except (PolicyError, yaml.YAMLError, OSError) as e:
                # 损坏的策略不能中断服务：回退默认值并记录安全事件
                try:
                    from .. import db
                    db.log_security("policy_invalid", f"策略文件无效，已回退默认策略: {type(e).__name__}")
                except Exception:
                    pass
        with self._lock:
            self._cache = deepcopy(policy)
            return deepcopy(policy)

    def validate_yaml(self, raw_yaml: str) -> tuple[dict, list[str]]:
        """校验 YAML 文本；返回 (policy, errors)。errors 非空即表单错误。"""
        errors: list[str] = []
        if not raw_yaml.strip():
            errors.append("policy: 内容为空")
            return default_policy(), errors
        try:
            data = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as e:
            return default_policy(), [f"policy: YAML 语法错误: {e}"]
        secrets = policy_contains_secrets(raw_yaml)
        if secrets:
            errors.append(f"policy: 策略不得包含密码/Token/API Key（命中规则 {secrets}）")
        try:
            policy = validate_policy(data if data is not None else {})
        except PolicyError as e:
            errors.append(str(e))
            return default_policy(), errors
        return policy, errors

    def save(self, raw_yaml: str) -> tuple[dict, list[str]]:
        """校验后原子写入；非法时返回表单错误，不影响现有服务与文件。"""
        policy, errors = self.validate_yaml(raw_yaml)
        if errors:
            return policy, errors
        self._write(policy, raw_yaml)
        return policy, []

    def _write(self, policy: dict, raw_yaml: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(raw_yaml, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        with self._lock:
            self._cache = deepcopy(policy)

    def dump(self) -> str:
        """当前生效策略的 YAML 文本（只读展示用，必不含秘密）。"""
        return yaml.safe_dump(self.load(), allow_unicode=True, sort_keys=False)

    def builtin_rules(self) -> list[dict]:
        """返回内置规则逐条启停状态。状态来源于当前生效策略。"""
        disabled = set(self.load().get("detection", {}).get("builtin_rules", {}).get("disabled", []) or [])
        return [{"name": name, "enabled": name not in disabled} for name in BUILTIN_RULE_NAMES]

    def set_builtin_rule(self, name: str, enabled: bool) -> dict:
        """切换单条内置规则，并通过策略校验后持久化到策略文件。"""
        if name not in BUILTIN_RULE_NAMES:
            raise PolicyError(f"未知内置规则 {name}")
        if not isinstance(enabled, bool):
            raise PolicyError("enabled: 必须是布尔值")
        policy = self.load()
        disabled = [n for n in policy["detection"]["builtin_rules"].get("disabled", []) if n != name]
        if not enabled:
            disabled.append(name)
        policy["detection"]["builtin_rules"]["disabled"] = disabled
        saved = validate_policy(policy)
        self._write(saved, yaml.safe_dump(saved, allow_unicode=True, sort_keys=False))
        return {"name": name, "enabled": name not in set(saved["detection"]["builtin_rules"]["disabled"])}
