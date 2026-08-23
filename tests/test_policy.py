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
    assert p["gate"]["confirm_before_llm"] == "on_findings"
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
    y = "gate:\n  confirm_before_llm: on_findings\n# token: sk-proj-abcdEFGH12345678901234567890\n"
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
    assert policy_contains_secrets("gate:\n  confirm_before_llm: on_findings\n") == []


def test_policy_rejects_bare_high_entropy_token(tmp_path):
    """策略中的裸高熵 Token（无已知前缀）由熵检测拦截。"""
    store = _store(tmp_path)
    y = "gate:\n  confirm_before_llm: on_findings\n# 疑似 token: X9kQm2vR7pT3sL8wN4\n"
    _, errors = store.save(y)
    assert errors and "不得包含" in errors[0]
    assert not store.path.exists()
