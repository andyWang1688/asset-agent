"""安全策略测试：默认值、校验（正则/长度/超时/白名单）、YAML 禁代码、策略禁秘密、损坏回退。"""
import yaml

import pytest

from app.security.detectors import ScanEngine
from app.security.policy import (
    DEFAULT_POLICY,
    PolicyError,
    PolicyStore,
    default_policy,
    policy_contains_secrets,
    validate_policy,
)


def _store(tmp_path) -> PolicyStore:
    return PolicyStore(tmp_path / "config" / "policy.yaml")


def test_default_policy_values():
    p = default_policy()
    assert p["gate"]["confirm_before_llm"] == "never"
    assert p["detection"]["entropy"]["min_length"] >= 8
    assert p["actions"]["defaults"]["pii"] == "redact"
    assert p["actions"]["defaults"]["credential"] == "store"


def test_builtin_rule_toggle_persists_and_reports_status(tmp_path):
    store = _store(tmp_path)
    before = {r["name"]: r["enabled"] for r in store.builtin_rules()}
    assert before["email"] is True
    result = store.set_builtin_rule("email", False)
    assert result == {"name": "email", "kind": "pii", "enabled": False}
    assert next(r for r in store.builtin_rules() if r["name"] == "email")["enabled"] is False
    reloaded = PolicyStore(store.path)
    assert next(r for r in reloaded.builtin_rules() if r["name"] == "email")["enabled"] is False
    assert not any(f.rule == "email" for f in ScanEngine(reloaded.load()).scan("user@example.com"))
    assert reloaded.set_builtin_rule("email", True)["enabled"] is True
    assert any(f.rule == "email" for f in ScanEngine(reloaded.load()).scan("user@example.com"))


def test_builtin_rule_toggle_rejects_unknown(tmp_path):
    with pytest.raises(PolicyError, match="未知内置规则"):
        _store(tmp_path).set_builtin_rule("not_a_rule", False)


def test_custom_rule_form_flow_persists_and_toggles(tmp_path):
    store = _store(tmp_path)
    created = store.add_custom_rule(
        {"name": "employee_id", "pattern": r"EMP-\d{6}", "kind": "pii", "validator": None}
    )
    assert created == {
        "name": "employee_id", "kind": "pii", "enabled": True,
        "validator": None, "confidence": 0.9,
    }
    assert any(f.rule == "employee_id" for f in ScanEngine(store.load()).scan("编号 EMP-123456"))

    store.set_custom_rule("employee_id", False)
    reloaded = PolicyStore(store.path)
    assert reloaded.custom_rules()[0]["enabled"] is False
    assert not any(f.rule == "employee_id" for f in ScanEngine(reloaded.load()).scan("编号 EMP-123456"))


def test_custom_rule_form_preserves_validation_guards(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(PolicyError, match="长度"):
        store.add_custom_rule({"name": "too_long", "pattern": "a" * 301, "kind": "pii"})
    with pytest.raises(PolicyError, match="白名单"):
        store.add_custom_rule(
            {"name": "bad_validator", "pattern": r"\d+", "kind": "pii", "validator": "os.system"}
        )


def test_custom_rules_have_no_count_limit():
    policy = default_policy()
    policy["detection"]["extra_rules"] = [
        {"name": f"rule_{i}", "pattern": rf"VALUE-{i}-\d+", "kind": "pii"}
        for i in range(101)
    ]
    assert len(validate_policy(policy)["detection"]["extra_rules"]) == 101


def test_structured_security_settings_roundtrip_and_preserve_deployment_fields(tmp_path):
    store = _store(tmp_path)
    before = store.load()

    updated = store.update_security_settings({
        "mode": "confirm",
        "keywords": {"enabled": False, "items": ["credential"]},
        "entropy": {"enabled": False, "sensitivity": "sensitive"},
    })

    assert updated == {
        "mode": "confirm",
        "keywords": {"enabled": False, "items": ["credential"]},
        "entropy": {"enabled": False, "sensitivity": "sensitive"},
    }
    policy = store.load()
    assert policy["gate"]["confirm_before_llm"] == "always"
    assert policy["detection"]["entropy"] == {
        **before["detection"]["entropy"],
        "enabled": False,
        "min_shannon": 3.2,
        "min_length": 12,
        "context_min_length": 10,
    }
    assert policy["actions"] == before["actions"]
    assert policy["detection"]["context"]["window"] == before["detection"]["context"]["window"]
    assert policy["detection"]["context"]["boost"] == before["detection"]["context"]["boost"]


def test_entropy_sensitivity_presets_and_custom_readback(tmp_path):
    store = _store(tmp_path)
    expected = {
        "sensitive": (3.2, 12, 10),
        "balanced": (3.5, 16, 12),
        "conservative": (4.0, 20, 16),
    }
    for name, values in expected.items():
        view = store.update_security_settings({"entropy": {"sensitivity": name}})
        entropy = store.load()["detection"]["entropy"]
        assert (entropy["min_shannon"], entropy["min_length"], entropy["context_min_length"]) == values
        assert view["entropy"]["sensitivity"] == name

    policy = store.load()
    policy["detection"]["entropy"]["min_shannon"] = 3.6
    saved = validate_policy(policy)
    store._write(saved, yaml.safe_dump(saved, allow_unicode=True, sort_keys=False))
    assert store.security_settings()["entropy"]["sensitivity"] == "custom"


def test_structured_keywords_immediately_change_detection(tmp_path):
    store = _store(tmp_path)
    text = "credential: Ab3dEf4gH7"
    store.update_security_settings({"keywords": {"enabled": True, "items": ["credential"]}})
    assert any(f.rule == "context_suspect_value" for f in ScanEngine(store.load()).scan(text))

    store.update_security_settings({"keywords": {"items": []}})
    assert ScanEngine(store.load()).scan(text) == []
    store.update_security_settings({"keywords": {"enabled": False, "items": ["credential"]}})
    assert ScanEngine(store.load()).scan(text) == []


def test_save_and_load_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.save("gate:\n  confirm_before_llm: always\n")
    loaded = store.load()
    assert loaded["gate"]["confirm_before_llm"] == "always"
    # 其余字段保持默认（深合并）
    assert loaded["detection"]["entropy"]["min_length"] == DEFAULT_POLICY["detection"]["entropy"]["min_length"]


def test_invalid_gate_mode_rejected(tmp_path):
    store = _store(tmp_path)
    policy, errors = store.save("gate:\n  confirm_before_llm: sometimes\n")
    assert errors and "gate.confirm_before_llm" in errors[0]
    assert not store.path.exists()  # 未写入


def test_invalid_regex_rejected(tmp_path):
    store = _store(tmp_path)
    y = "detection:\n  extra_rules:\n    - name: bad\n      pattern: '([a-z'\n      kind: credential\n"
    policy, errors = store.save(y)
    assert errors and "pattern" in errors[0]


def test_pattern_too_long_rejected(tmp_path):
    store = _store(tmp_path)
    pattern = "a" * 301
    y = f"detection:\n  extra_rules:\n    - name: bad\n      pattern: '{pattern}'\n      kind: credential\n"
    _, errors = store.save(y)
    assert errors and "长度" in errors[0]


def test_pattern_matching_empty_rejected(tmp_path):
    store = _store(tmp_path)
    y = "detection:\n  extra_rules:\n    - name: empty\n      pattern: 'a*'\n      kind: credential\n"
    _, errors = store.save(y)
    assert errors and "空串" in errors[0]


def test_catastrophic_pattern_timeout_rejected(tmp_path):
    store = _store(tmp_path)
    y = (
        "detection:\n  extra_rules:\n    - name: re\n"
        "      pattern: '(a+)+$'\n      kind: credential\n"
    )
    _, errors = store.save(y)
    assert errors  # 超时或执行异常均拒绝


def test_unknown_validator_rejected(tmp_path):
    store = _store(tmp_path)
    y = (
        "detection:\n  extra_rules:\n    - name: v\n      pattern: '[0-9]+'\n"
        "      kind: credential\n      validator: os.system\n"
    )
    _, errors = store.save(y)
    assert errors and "白名单" in errors[0]


def test_builtin_validator_allowed(tmp_path):
    store = _store(tmp_path)
    y = (
        "detection:\n  extra_rules:\n    - name: v\n      pattern: '[0-9]{16}'\n"
        "      kind: pii\n      validator: luhn\n"
    )
    _, errors = store.save(y)
    assert errors == []


def test_unknown_builtin_rule_disabled_rejected(tmp_path):
    store = _store(tmp_path)
    _, errors = store.save("detection:\n  builtin_rules:\n    disabled: [no_such_rule]\n")
    assert errors and "未知内置规则" in errors[0]


def test_entropy_params_out_of_range_rejected(tmp_path):
    store = _store(tmp_path)
    _, errors = store.save("detection:\n  entropy:\n    min_shannon: 9\n")
    assert errors and "min_shannon" in errors[0]


def test_pii_default_store_rejected(tmp_path):
    store = _store(tmp_path)
    _, errors = store.save("actions:\n  defaults:\n    pii: store\n")
    assert errors and "pii" in errors[0]


def test_yaml_python_tag_rejected(tmp_path):
    store = _store(tmp_path)
    y = "gate:\n  confirm_before_llm: !!python/object/apply:os.system ['echo hacked']\n"
    _, errors = store.save(y)
    assert errors  # safe_load 拒绝任意代码标签


def test_policy_must_not_contain_secrets(tmp_path):
    store = _store(tmp_path)
    y = "gate:\n  confirm_before_llm: always\n# token: sk-proj-abcdEFGH12345678901234567890\n"
    _, errors = store.save(y)
    assert errors and "不得包含" in errors[0]
    assert not store.path.exists()


def test_policy_must_not_contain_key_value_secret(tmp_path):
    store = _store(tmp_path)
    y = "detection:\n  context:\n    keywords: [password]\n# password=Sup3rSecret!\n"
    _, errors = store.save(y)
    assert errors and "不得包含" in errors[0]


def test_rule_pattern_text_not_treated_as_secret(tmp_path):
    # pattern 行是正则源码而非数据，不应被误判为策略中的秘密
    store = _store(tmp_path)
    y = (
        "detection:\n  extra_rules:\n    - name: kv\n"
        "      pattern: 'token=[A-Za-z0-9]{20}'\n      kind: credential\n"
    )
    _, errors = store.save(y)
    assert errors == []


def test_invalid_policy_file_falls_back_to_default(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("gate: [不是映射\n", encoding="utf-8")
    loaded = store.load()
    assert loaded == default_policy()  # 服务不中断


def test_validate_policy_rejects_non_dict():
    with pytest.raises(PolicyError):
        validate_policy("字符串")


def test_policy_contains_secrets_helper():
    hits = policy_contains_secrets("api_key: sk-proj-abcdEFGH12345678901234567890\n")
    assert "openai_key" in hits
    assert policy_contains_secrets("gate:\n  confirm_before_llm: always\n") == []


def test_policy_rejects_bare_high_entropy_token(tmp_path):
    """策略中的裸高熵 Token（无已知前缀）由熵检测拦截。"""
    store = _store(tmp_path)
    y = "gate:\n  confirm_before_llm: always\n# 疑似 token: X9kQm2vR7pT3sL8wN4\n"
    _, errors = store.save(y)
    assert errors and "不得包含" in errors[0]
    assert not store.path.exists()


# ---- 内置规则覆盖层（#18）----

def _scan(policy: dict, text: str):
    return ScanEngine(policy).scan(text)


def test_builtin_override_changes_detection_immediately(tmp_path):
    store = _store(tmp_path)
    text = "联系 13800138000 谢谢"
    # 覆盖前：手机号命中内置 mobile_phone_cn（pii）
    before = _scan(store.load(), text)
    assert any(f.rule == "mobile_phone_cn" and f.kind == "pii" for f in before)

    # 覆盖正则：只匹配 139 开头；原规则停用
    store.set_builtin_override("mobile_phone_cn", pattern=r"(?<!\d)139\d{8}(?!\d)")
    policy = store.load()
    assert policy["detection"]["builtin_rules"]["overrides"]["mobile_phone_cn"]["pattern"]
    after = _scan(policy, text)
    assert not any(f.rule == "mobile_phone_cn" for f in after)  # 138 不再命中
    assert any(f.rule == "mobile_phone_cn" for f in _scan(policy, "联系 13900139000"))

    # 覆盖即时生效（新 store 读同一文件）
    reloaded = PolicyStore(store.path)
    assert not any(f.rule == "mobile_phone_cn" for f in _scan(reloaded.load(), text))


def test_builtin_override_kind_only(tmp_path):
    store = _store(tmp_path)
    store.set_builtin_override("mobile_phone_cn", kind="credential")
    f = _scan(store.load(), "联系 13800138000")
    hit = next(x for x in f if x.rule == "mobile_phone_cn")
    assert hit.kind == "credential"
    assert hit.suggested_action == "store"  # credential 默认 store


def test_builtin_override_restore_returns_to_default(tmp_path):
    store = _store(tmp_path)
    store.set_builtin_override("mobile_phone_cn", pattern=r"(?<!\d)139\d{8}(?!\d)")
    assert not any(f.rule == "mobile_phone_cn" for f in _scan(store.load(), "13800138000"))
    store.restore_builtin_rule("mobile_phone_cn")
    policy = store.load()
    assert policy["detection"]["builtin_rules"]["overrides"] == {}
    assert any(f.rule == "mobile_phone_cn" for f in _scan(policy, "13800138000"))


def test_builtin_override_restore_rejects_unknown_and_unoverridden(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(PolicyError, match="未知内置规则"):
        store.restore_builtin_rule("nope")
    with pytest.raises(PolicyError, match="未被覆盖"):
        store.restore_builtin_rule("email")


def test_builtin_override_requires_pattern_or_kind(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(PolicyError, match="至少"):
        store.set_builtin_override("email")


def test_builtin_override_guardrails(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(PolicyError, match="未知内置规则"):
        store.set_builtin_override("nope", pattern=r"\d+")
    with pytest.raises(PolicyError, match="长度"):
        store.set_builtin_override("email", pattern="a" * 301)
    with pytest.raises(PolicyError, match="非法正则"):
        store.set_builtin_override("email", pattern="([a-z")
    with pytest.raises(PolicyError, match="空串"):
        store.set_builtin_override("email", pattern="a*")
    with pytest.raises(PolicyError, match="类别|必须是"):
        store.set_builtin_override("email", kind="not_a_kind")
    # 灾难性回溯：经 YAML 保存路径同样被拦截
    y = (
        "detection:\n  builtin_rules:\n    overrides:\n      email:\n"
        "        pattern: '(a+)+$'\n"
    )
    _, errors = store.save(y)
    assert errors
    # 非法覆盖不落盘、不影响现有策略
    assert PolicyStore(store.path).load()["detection"]["builtin_rules"]["overrides"] == {}


def test_builtin_override_yaml_conflict_with_disabled_rejected(tmp_path):
    store = _store(tmp_path)
    y = (
        "detection:\n  builtin_rules:\n    disabled: [email]\n    overrides:\n"
        "      email:\n        pattern: 'x@y\\.com'\n"
    )
    _, errors = store.save(y)
    assert errors and "disabled" in errors[0]


def test_rules_detail_sources_and_fields(tmp_path):
    store = _store(tmp_path)
    store.add_custom_rule({"name": "emp_id", "pattern": r"EMP-\d{6}", "kind": "pii"})
    store.set_builtin_override("mobile_phone_cn", pattern=r"(?<!\d)139\d{8}(?!\d)")
    detail = {r["name"]: r for r in store.rules_detail()}
    # 字段齐全
    for r in detail.values():
        for key in ("name", "kind", "description", "examples", "pattern", "source", "enabled"):
            assert key in r
    assert detail["email"]["source"] == "builtin"
    assert detail["mobile_phone_cn"]["source"] == "override"
    assert detail["emp_id"]["source"] == "custom"
    # 内置规则带中文描述与示例
    assert detail["email"]["description"]
    assert detail["email"]["examples"]
    # 覆盖后返回覆盖正则
    assert detail["mobile_phone_cn"]["pattern"] == r"(?<!\d)139\d{8}(?!\d)"


def test_builtin_metadata_covers_all_rules():
    from app.security.rules import BUILTIN_RULE_NAMES, RULE_METADATA
    assert set(RULE_METADATA) == set(BUILTIN_RULE_NAMES)
    for name, meta in RULE_METADATA.items():
        assert meta["description"] and meta["examples"], name


def test_unoverridden_builtin_rules_behavior_unchanged(tmp_path):
    store = _store(tmp_path)
    text = "邮箱 user@example.com 手机 13800138000"
    default_findings = {(f.rule, f.kind) for f in _scan(default_policy(), text)}
    store_findings = {(f.rule, f.kind) for f in _scan(store.load(), text)}
    assert default_findings == store_findings
