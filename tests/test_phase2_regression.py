"""第二批复审回归：私密引用跨资料唯一、元数据不泄漏笔记正文、
编辑校验按提交策略快照、伪造标签不复扫旁路、值哈希去重不覆盖目标、
整理要求敏感值不静默丢弃。"""
import base64
import json
from dataclasses import asdict

import pytest

from app import db
from app.credentials.vaultwarden import VaultwardenAdapter
from app.ingest import receiver
from app.security import redactor, submissions
from app.security.detectors import ScanEngine
from app.security.policy import PolicyStore
from tests.fakes import FakeCredentialStore, FakeProvider
from tests.fakes import ingest_and_finish


def _store(settings):
    return PolicyStore(settings.policy_file)


@pytest.fixture(autouse=True)
def _knowledge_model_configured(workspace):
    db.upsert_model_config(None, "test-knowledge", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "knowledge")


async def _submit(settings, creds, sid, text, mode="confirm"):
    db.create_session(sid, "maintain")
    store = _store(settings)
    store.update_security_settings({"mode": mode})
    result = await ingest_and_finish(
        settings, creds, text=text, session_id=sid, policy_store=store,
        knowledge_provider_getter=lambda: FakeProvider("{}"),
    )
    return store, result


def _memory_bw_adapter(settings, monkeypatch):
    adapter = VaultwardenAdapter(settings)
    items = []

    async def ready():
        pass

    async def fake_run(*args, stdin=None, **kwargs):
        if args == ("get", "template", "item"):
            return json.dumps({"name": "", "notes": "", "type": 1, "login": {}})
        if args == ("encode",):
            return base64.b64encode(stdin.encode()).decode()
        if args[:2] == ("create", "item"):
            item = json.loads(base64.b64decode(args[2]).decode())
            item["id"] = "fixture-item-" + str(len(items) + 1)
            items.append(item)
            return json.dumps(item)
        if args == ("sync",):
            return ""
        if args == ("list", "items"):
            return json.dumps(items)
        raise AssertionError("unexpected fake bw operation: " + str(args))

    monkeypatch.setattr(adapter, "_ensure_ready", ready)
    monkeypatch.setattr(adapter, "_run", fake_run)
    return adapter, items


async def test_ref_id_distinct_across_documents(settings):
    creds = FakeCredentialStore()
    _, first = await _submit(settings, creds, "refs-a", "password=AlphaSecret12!", "default")
    _, second = await _submit(settings, creds, "refs-b", "password=BravoSecret34!", "default")
    a = db.report_view(first["report_id"])["entries"][0]
    b = db.report_view(second["report_id"])["entries"][0]
    assert a["vault"]["item_id"] != b["vault"]["item_id"]
    assert a["ref_id"] != b["ref_id"]


async def test_vault_metadata_no_note_body(settings, monkeypatch):
    secret = "fixture-private-note-body-not-metadata"
    adapter = VaultwardenAdapter(settings)

    async def ready():
        pass

    async def fake_run(*args, **kwargs):
        if args == ("sync",):
            return ""
        assert args == ("list", "items")
        return json.dumps([{"id": "note-one", "type": 2, "name": "Personal note",
                            "notes": secret, "secureNote": {"type": 0}}])

    monkeypatch.setattr(adapter, "_ensure_ready", ready)
    monkeypatch.setattr(adapter, "_run", fake_run)
    result = await adapter.list_items()
    assert secret not in json.dumps([asdict(m) for m in result])


async def test_metadata_edit_honors_custom_rule(settings):
    store = _store(settings)
    store.add_custom_rule({"name": "local_pin", "pattern": r"LOCAL-PIN:\d{4}", "kind": "credential"})
    creds = FakeCredentialStore()
    store, draft = await _submit(settings, creds, "metadata-custom", "password=FixtureOriginal!")
    secret = "LOCAL-PIN:4826"
    assert await ScanEngine(store.load()).scan_async(secret)
    fid = draft["findings"][0]["id"]
    try:
        await submissions.confirm(settings, creds, store, draft["submission_id"], {fid: "store"},
                                  edits={fid: {"description": secret}}, session_id="metadata-custom",
                                  knowledge_provider_getter=lambda: FakeProvider("{}"))
    except (ValueError, submissions.SubmissionError):
        pass
    assert secret not in json.dumps(db.report_view(draft["report_id"]))


async def test_metadata_edit_honors_entropy(settings):
    creds = FakeCredentialStore()
    store, draft = await _submit(settings, creds, "metadata-a", "password=FixtureOriginal!")
    new_secret = "L8vQw2nZ7pJ4tB6xD9rS"
    assert await ScanEngine(store.load()).scan_async(new_secret)
    fid = draft["findings"][0]["id"]
    try:
        await submissions.confirm(settings, creds, store, draft["submission_id"], {fid: "store"},
                                  edits={fid: {"description": new_secret}}, session_id="metadata-a",
                                  knowledge_provider_getter=lambda: FakeProvider("{}"))
    except (ValueError, submissions.SubmissionError):
        pass
    assert new_secret not in json.dumps(db.report_view(draft["report_id"]))


async def test_forged_private_label_rejected(settings):
    creds = FakeCredentialStore()
    store, draft = await _submit(settings, creds, "preview-a", "password=FixtureOriginal!")
    fid = draft["findings"][0]["id"]
    secret = "FixtureInjectedSecret!"
    injected = "[🔒 password=" + secret + "](private:invented_reference)"
    try:
        await submissions.confirm(settings, creds, store, draft["submission_id"], {fid: "store"},
                                  edited_text=injected, session_id="preview-a",
                                  knowledge_provider_getter=lambda: FakeProvider("{}"))
    except (ValueError, submissions.SubmissionError):
        pass
    assert secret not in json.dumps(db.report_view(draft["report_id"]))


@pytest.mark.parametrize("secret", ["L8vQw2nZ7pJ4tB6xD9rS", "11010519491231002X"])
async def test_well_shaped_unknown_reference_is_not_trusted(settings, secret):
    creds = FakeCredentialStore()
    store, draft = await _submit(settings, creds, "unknown-shaped-ref", "password=FixtureOriginal!")
    assert await ScanEngine(store.load()).scan_async(secret)
    fid = draft["findings"][0]["id"]
    injected = "[🔒 " + secret + "](private:pr_0000000000000000)"
    try:
        await submissions.confirm(settings, creds, store, draft["submission_id"], {fid: "store"},
                                  edited_text=injected, session_id="unknown-shaped-ref",
                                  knowledge_provider_getter=lambda: FakeProvider("{}"))
    except (ValueError, submissions.SubmissionError):
        pass
    assert secret not in json.dumps(db.report_view(draft["report_id"]))


@pytest.mark.parametrize("secret", ["L8vQw2nZ7pJ4tB6xD9rS", "11010519491231002X"])
def test_output_scan_does_not_trust_sensitive_private_label(secret):
    forged = "[🔒 " + secret + "](private:pr_0000000000000000)"
    clean, _ = redactor.sanitize_llm_output(forged)
    assert secret not in clean


async def test_report_target_not_overridden_by_dedup(settings, monkeypatch):
    creds, stored_items = _memory_bw_adapter(settings, monkeypatch)
    _, first = await _submit(settings, creds, "target-a", "password=FixtureShared! first document", "default")
    first_entry = db.report_view(first["report_id"])["entries"][0]
    store, second = await _submit(settings, creds, "target-b", "password=FixtureShared! second document")
    fid = second["findings"][0]["id"]
    await submissions.confirm(settings, creds, store, second["submission_id"], {fid: "store"},
                              edits={fid: {"vault_kind": "secure_note", "vault_name": "Another Note",
                                           "field_name": "Private field"}},
                              session_id="target-b", knowledge_provider_getter=lambda: FakeProvider("{}"))
    second_entry = db.report_view(second["report_id"])["entries"][0]
    assert second_entry["vault"]["kind"] == "secure_note"
    assert second_entry["vault"]["item_id"] != first_entry["vault"]["item_id"]
    assert any(p["type"] == 2 and p["name"] == "Another Note" for p in stored_items)


async def test_sensitive_instruction_saved(settings):
    db.create_session("instruction-a", "maintain")
    store = _store(settings)
    store.update_security_settings({"mode": "default"})
    creds = FakeCredentialStore()
    secret = "FixtureInstructionSecret!"
    result = await ingest_and_finish(
        settings, creds, filename="fixture.txt", data=b"ordinary file document",
        instruction="process this password=" + secret, session_id="instruction-a",
        policy_store=store, knowledge_provider_getter=lambda: FakeProvider("{}"),
    )
    assert any(p.value == secret for p in creds.created)
    report = db.report_view(result["report_id"])
    assert report["entries"]
    assert secret not in json.dumps(report)


async def test_repeated_secret_keeps_every_finding_reference_resolvable(settings):
    creds = FakeCredentialStore()
    _, result = await _submit(settings, creds, "repeated-ref",
                              "password=FixtureRepeat!\npassword=FixtureRepeat!", "default")
    entries = db.report_view(result["report_id"])["entries"]
    assert len(entries) == 2
    assert len(creds.created) == 1
    assert all(e["vault"]["saved"] and e["vault"]["item_id"] for e in entries)
    assert len({e["vault"]["item_id"] for e in entries}) == 1
