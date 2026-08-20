from app.security import redactor
from app.security.rules import scan_text

SECRET = "Sup3rSecret!"


def test_password_assignment():
    text = "生产数据库 host=10.0.0.8，user=app，password=Sup3rSecret!，用于订单服务。"
    findings = scan_text(text)
    values = [f.value for f in findings]
    assert SECRET in values
    f = next(f for f in findings if f.value == SECRET)
    assert f.rule == "key_value_secret"
    assert f.key_hint.lower() == "password"


def test_build_refs_replaces_and_keeps_rest():
    text = "生产数据库 host=10.0.0.8，user=app，password=Sup3rSecret!，用于订单服务。"
    sanitized, refs = redactor.build_refs(text)
    assert SECRET not in sanitized
    assert "[SECRET_REF:password]" in sanitized
    assert "10.0.0.8" in sanitized
    assert refs[0]["value"] == SECRET


def test_openai_key_and_connection_string():
    text = "api_key=sk-proj-abcdEFGH12345678901234567890\npostgres://user:pass1234@10.0.0.8:5432/db"
    findings = scan_text(text)
    rules = {f.rule for f in findings}
    assert "db_connection_string" in rules
    # api_key= 与 openai_key 重叠 → 合并为一个 Finding（类别 credential），证据保留两条规则
    key_value = [f for f in findings if f.rule == "key_value_secret"]
    assert key_value and key_value[0].kind == "credential"
    assert "openai_key" in key_value[0].evidence


def test_id_card_and_bank_card():
    text = "身份证 11010519491231002X，银行卡 4111111111111111"
    rules = {f.rule for f in scan_text(text)}
    assert "id_card" in rules
    assert "bank_card" in rules


def test_invalid_id_not_flagged():
    text = "身份证 110105194912310021"  # 校验位错误
    rules = {f.rule for f in scan_text(text)}
    assert "id_card" not in rules


def test_private_key_block():
    text = "密钥：-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----\n结束"
    findings = scan_text(text)
    assert any(f.rule == "private_key_block" for f in findings)
    sanitized, _ = redactor.build_refs(text)
    assert "PRIVATE KEY" not in sanitized


def test_recovery_code():
    text = "恢复码：ABCD-EFGH-IJKL-MNOP-QRST"
    assert any(f.rule == "recovery_code" for f in scan_text(text))


def test_same_value_two_places_one_ref():
    text = "password=Sup3rSecret! 再次输入 Sup3rSecret!"
    sanitized, refs = redactor.build_refs(text)
    assert SECRET not in sanitized
    assert len([r for r in refs if r["value"] == SECRET]) == 1


def test_sanitize_llm_output_strips():
    out, hits = redactor.sanitize_llm_output("答案是 password=Sup3rSecret! 不要用")
    assert SECRET not in out
    assert "key_value_secret" in hits
