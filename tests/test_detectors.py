"""检测模型测试：统一 Finding、规则、上下文、熵值、合并去重、禁用/自定义规则、失败阻断。"""
import pytest

from app.security.detectors import DetectorError, ScanEngine, merge_findings, shannon_entropy
from app.security.policy import default_policy
from app.security.rules import (
    KIND_CREDENTIAL,
    KIND_PII,
    KIND_UNKNOWN,
    Finding,
    scan_text,
)

SECRET = "Sup3rSecret!"


def _engine(patch: dict | None = None) -> ScanEngine:
    return ScanEngine(patch or {})


def test_unified_finding_fields():
    f = next(x for x in scan_text("password=Sup3rSecret!") if x.value == SECRET)
    for attr in ("id", "kind", "rule", "span", "confidence", "evidence", "suggested_action", "detector"):
        assert getattr(f, attr) is not None
    assert f.kind == KIND_CREDENTIAL
    assert f.detector == "regex"
    assert 0 < f.confidence <= 1
    assert f.span == (f.start, f.end)


def test_kind_mapping_pii():
    findings = scan_text("身份证 11010519491231002X")
    assert findings and findings[0].kind == KIND_PII


def test_email_detected_as_pii():
    findings = scan_text("联系邮箱 user.name+alerts@example.com")
    email = next(f for f in findings if f.rule == "email")
    assert email.kind == KIND_PII
    assert email.value == "user.name+alerts@example.com"


def test_mobile_phone_detected_as_pii():
    findings = scan_text("联系电话 13812345678")
    mobile = next(f for f in findings if f.rule == "mobile_phone_cn")
    assert mobile.kind == KIND_PII
    assert mobile.value == "13812345678"


def test_invalid_email_and_plain_long_digits_not_flagged_as_pii():
    text = "无效邮箱 a..b@example.com，普通编号 12345678901，长数字 20260822123456789012"
    assert not [f for f in scan_text(text) if f.kind == KIND_PII]


def test_email_and_mobile_rules_can_be_disabled():
    policy = default_policy()
    policy["detection"]["builtin_rules"]["disabled"] = ["email", "mobile_phone_cn"]
    findings = ScanEngine(policy).scan("联系 user@example.com 或 13812345678")
    assert not [f for f in findings if f.rule in {"email", "mobile_phone_cn"}]


def test_db_password_api_key_connection_string_detected():
    text = (
        "db password=Sup3rSecret!\n"
        "openai: sk-proj-abcdEFGH12345678901234567890\n"
        "dsn: postgres://user:pass1234@10.0.0.8:5432/db\n"
    )
    findings = scan_text(text)
    assert {f.kind for f in findings} == {KIND_CREDENTIAL}
    assert len(findings) >= 3


def test_normal_uuid_and_hash_not_flagged():
    text = "UUID 550e8400-e29b-41d4-a716-446655440000，哈希 3f2a9c1d8e4b7f6a5d3c2b1a9e8f7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f"
    assert scan_text(text) == []


def test_chinese_plain_text_not_flagged():
    text = "这是普通的中文文本，介绍订单服务与缓存，描述项目背景与团队分工。"
    assert scan_text(text) == []


def test_context_raises_confidence():
    bare = next(f for f in scan_text("sk-proj-abcdEFGH12345678901234567890") if f.rule == "openai_key")
    with_ctx = next(
        f for f in scan_text("服务器 password=sk-proj-abcdEFGH12345678901234567890") if f.value.startswith("sk-proj")
    )
    assert with_ctx.confidence > bare.confidence


def test_context_keyword_value_new_finding():
    findings = scan_text("部署密钥 A1b2C3d4E5f6G7h8I9j0，注意保管")
    assert any(f.rule == "context_keyword_value" for f in findings)
    f = next(f for f in findings if f.rule == "context_keyword_value")
    assert f.kind == KIND_CREDENTIAL
    assert f.value == "A1b2C3d4E5f6G7h8I9j0"


def test_entropy_standalone_token_is_unknown_suspect():
    findings = scan_text("一串可疑内容 X9kQm2vR7pT3sL8wN4 结束")
    suspects = [f for f in findings if f.value == "X9kQm2vR7pT3sL8wN4"]
    assert suspects and suspects[0].kind == KIND_UNKNOWN
    assert suspects[0].rule == "entropy_token"


def test_entropy_short_string_never_credential_alone():
    # 短高熵字符串单独出现：不得判为凭证，也不得产生 Finding
    assert scan_text("aB3$xY9") == []


def test_entropy_with_context_upgrades_to_credential():
    # 无 =/: 分隔符（key_value 规则不命中），熵 + 上下文 → credential
    findings = scan_text("access token X9kQm2vR7pT3sL8wN4")
    f = next((x for x in findings if x.value == "X9kQm2vR7pT3sL8wN4"), None)
    assert f is not None and f.kind == KIND_CREDENTIAL


def test_merge_overlap_dedup_one_finding():
    # key_value 与 openai_key 重叠 → 合并为一个 Finding，置信度取最高，证据合并
    findings = scan_text("password=sk-proj-abcdEFGH12345678901234567890")
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == KIND_CREDENTIAL
    assert "key_value_secret" in f.evidence and "openai_key" in f.evidence


def test_merge_later_layer_only_tightens_or_adds():
    f1 = Finding(id="a", kind=KIND_UNKNOWN, rule="x", span=(0, 10), confidence=0.5,
                 evidence="e1", suggested_action="redact", detector="d1", value="v")
    f2 = Finding(id="b", kind=KIND_UNKNOWN, rule="y", span=(5, 15), confidence=0.4,
                 evidence="e2", suggested_action="redact", detector="d2", value="v")
    f3 = Finding(id="c", kind=KIND_CREDENTIAL, rule="z", span=(20, 30), confidence=0.9,
                 evidence="e3", suggested_action="store", detector="d3", value="w")
    merged = merge_findings([f1, f2, f3])
    assert len(merged) == 2  # 重叠组一个 + 独立组一个
    group = next(m for m in merged if m.span[0] == 0)
    assert group.confidence == 0.5  # 取组内最高，不降低
    assert group.evidence == "e1；e2"
    assert merged[1].kind == KIND_CREDENTIAL


def test_disabled_builtin_rule():
    policy = default_policy()
    policy["detection"]["entropy"]["enabled"] = False
    policy["detection"]["builtin_rules"]["disabled"] = ["openai_key", "key_value_secret"]
    findings = ScanEngine(policy).scan("sk-proj-abcdEFGH12345678901234567890")
    assert findings == []


def test_extra_rule_from_policy():
    policy = default_policy()
    policy["detection"]["extra_rules"] = [
        {"name": "internal_host", "pattern": r"\b10\.0\.0\.\d{1,3}\b", "kind": KIND_PII, "confidence": 0.7}
    ]
    findings = ScanEngine(policy).scan("服务器地址 10.0.0.8 与 10.0.0.9")
    assert [f.rule for f in findings] == ["internal_host", "internal_host"]
    assert all(f.detector == "regex" for f in findings)


def test_entropy_params_min_length():
    # 长度 16 的 token 在 min_length=17 时不再命中熵检测
    tok = "X9kQm2vR7pT3sL8w"  # 16 字符
    assert any(f.value == tok for f in scan_text(f"值 {tok} 结束"))
    policy = default_policy()
    policy["detection"]["entropy"]["min_length"] = 17
    assert all(f.value != tok for f in ScanEngine(policy).scan(f"值 {tok} 结束"))


def test_shannon_entropy_basics():
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("ab") > shannon_entropy("aa")


def test_basic_detector_failure_blocks(monkeypatch):
    from app.security import detectors

    class BrokenDetector:
        name = "broken"
        critical = True

        def detect(self, text, ctx, on_warning=None):
            raise DetectorError("boom")

    monkeypatch.setattr(detectors, "RegexRulesDetector", lambda: BrokenDetector())
    with pytest.raises(DetectorError):
        ScanEngine(default_policy()).scan("任意内容 password=abc")
