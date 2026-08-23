"""本地敏感信息识别规则与统一 Finding。

新增规则：在 RULES 列表追加 (规则名, 正则, 类型, [校验函数]) 即可。
类型（kind）既可以是规范类别（credential / pii），也可以是历史细分名
（api_key / token / password / id_card …），会自动归一化到统一类别：
credential、pii、unknown_suspect；无命中即 plain（不产生 Finding）。
"""
from dataclasses import dataclass

KIND_CREDENTIAL = "credential"
KIND_PII = "pii"
KIND_UNKNOWN = "unknown_suspect"
KINDS = (KIND_CREDENTIAL, KIND_PII, KIND_UNKNOWN)

# 用户在确认页可选择的裁决动作
ACTION_STORE = "store"    # 存入 Vaultwarden 并脱敏
ACTION_REDACT = "redact"  # 仅脱敏
ACTION_ALLOW = "allow"    # 标记误报并放行
ACTIONS = (ACTION_STORE, ACTION_REDACT, ACTION_ALLOW)


@dataclass(frozen=True)
class Finding:
    """统一 Finding：所有检测器输出该结构，合并去重后进入确认闸门。"""

    id: str
    kind: str            # credential | pii | unknown_suspect
    rule: str
    span: tuple[int, int]
    confidence: float
    evidence: str
    suggested_action: str  # store | redact | allow
    detector: str
    value: str = ""
    key_hint: str | None = None

    @property
    def start(self) -> int:
        return self.span[0]

    @property
    def end(self) -> int:
        return self.span[1]


def _id_card_valid(num: str) -> bool:
    if len(num) != 18:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check = "10X98765432"
    total = sum(int(n) * w for n, w in zip(num[:17], weights))
    return check[total % 11] == num[17].upper()


def _luhn_valid(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# 策略内置规则可引用的校验函数白名单（自定义规则只能从这里选，禁止任意代码）
VALIDATORS = {"id_card": _id_card_valid, "luhn": _luhn_valid}

_KEY_VALUE_PATTERN = (
    r"(?i)(?P<key>password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"client[_-]?secret|密码|口令)\s*[:=]\s*[\"']?(?P<value>[^\s,;，；\"'`]+)"
)

RULES: list[tuple] = [
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", "api_key"),
    ("google_api_key", r"\bAIza[0-9A-Za-z\-_]{35}\b", "api_key"),
    ("github_token", r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b", "token"),
    ("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", "api_key"),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", "api_key"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "token"),
    ("stripe_key", r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b", "api_key"),
    ("jwt_token", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b", "token"),
    ("private_key_block", r"-----BEGIN (?:[A-Z0-9 ]*)?PRIVATE KEY-----[\s\S]{20,2000}?-----END (?:[A-Z0-9 ]*)?PRIVATE KEY-----", "private_key"),
    ("db_connection_string", r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|clickhouse|oracle)://[^\s\"'`]+:[^\s\"'`@]+@[^\s\"'`]+", "connection_string"),
    ("email", r"(?i)(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])[A-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}(?![A-Z0-9-])", KIND_PII),
    ("mobile_phone_cn", r"(?<!\d)1[3-9]\d{9}(?!\d)", KIND_PII),
    ("id_card", r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]\b", "id_card", _id_card_valid),
    ("bank_card", r"\b\d{16,19}\b", "bank_card", _luhn_valid),
    ("recovery_code", r"\b[A-Z0-9]{4,6}(?:[ -][A-Z0-9]{4,6}){4,}\b", "recovery_code"),
    ("key_value_secret", _KEY_VALUE_PATTERN, "password"),
]

BUILTIN_RULE_NAMES = [r[0] for r in RULES]

# 历史细分类型 → 统一类别
_LEGACY_KIND_MAP = {
    "api_key": KIND_CREDENTIAL,
    "token": KIND_CREDENTIAL,
    "private_key": KIND_CREDENTIAL,
    "connection_string": KIND_CREDENTIAL,
    "password": KIND_CREDENTIAL,
    "recovery_code": KIND_CREDENTIAL,
    "secret": KIND_CREDENTIAL,
    "id_card": KIND_PII,
    "bank_card": KIND_PII,
}


def canonical_kind(kind: str) -> str:
    if kind in KINDS:
        return kind
    return _LEGACY_KIND_MAP.get(kind, KIND_UNKNOWN)


_TRIM = ".,;:!?)]}》】\"'`"
# 键值式秘密（password=xxx）：逗号/分号多为句读，但 !.?)] 等可能是密码字符，只裁句读与引号
_TRIM_KV = ",;，；\"'` "


def scan_text(text: str, policy: dict | None = None) -> list[Finding]:
    """兼容入口：扫描文本，返回统一 Finding 列表（同一位置只报一次）。"""
    from .detectors import ScanEngine  # 局部导入避免循环依赖

    return ScanEngine(policy or {}).scan(text)
