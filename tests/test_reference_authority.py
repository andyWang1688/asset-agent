"""引用信任回归测试：只有精确登记（sources.secret_refs 元数据）才豁免私密引用。

- 无可信登记时，rule-hash 形状与普通正文都完整执行安全检测。
- 提供 valid（含空集合）时只屏蔽精确登记的引用。
- 登记引用原样通过 Raw 复扫 / Wiki 编译 / 问答输出；伪造标签不豁免。
"""
import json

import pytest

from app import db
from app.crypto import sha256_hex
from app.query import service
from app.security import redactor
from app.security.rules import scan_text
from app.worker import Worker
from app.wiki import compiler
from tests.fakes import FakeCredentialStore, FakeProvider, SequenceProvider


REGISTERED_NAME = "private_key_block-cafe1234"
REGISTERED_REF_ID = "pr_0123456789abcdef"


# ---- 等价控制代理用例：形状不是来源权限 ----

@pytest.mark.parametrize(
    "value",
    ["11010519491231002x-00000000", "l8vqw2nz7pj4tb6xd9rs-00000000", "pr_0123456789abcdef"],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_rule_hash_shape_is_not_trust(value, wrapped):
    assert scan_text(value), "fixture must match the real detectors"
    text = redactor.private_ref(value, "pr_0000000000000000") if wrapped else value
    clean, _ = redactor.sanitize_llm_output(text)
    assert value.split("-")[0] not in clean


def test_valid_empty_is_no_exemption():
    fake = redactor.private_ref("11010519491231002x", "pr_0000000000000000")
    assert redactor.mask_placeholders(fake, valid=set()) == fake


def test_registered_reference_survives_strict_rescan():
    registered = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    masked = redactor.mask_placeholders(registered, valid={registered})
    assert len(masked) == len(registered)
    assert not scan_text(masked)


def test_registered_refs_reconstructs_from_metadata():
    secret_refs = json.dumps([{"name": REGISTERED_NAME, "ref_id": REGISTERED_REF_ID}])
    ref = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    assert redactor.registered_refs(secret_refs) == {ref}
    assert redactor.registered_refs("[]") == set()
    assert redactor.registered_refs("not-json") == set()


def _register_source(settings, name: str, ref_id: str) -> int:
    secret_refs = json.dumps([{"name": name, "ref_id": ref_id}])
    sha = sha256_hex(f"fixture-{name}-{ref_id}")
    source_id = db.insert_source(sha, "text", "fixture.txt", "", secret_refs, confirmed=0)
    db.update_source_processed(source_id, str(settings.inbox_dir / "fixture.md"), secret_refs, "[]")
    return source_id


# ---- Raw 编译复扫：只信任登记引用 ----

async def test_worker_rescan_trusts_only_registered_refs(settings):
    worker = Worker(settings, FakeCredentialStore(), lambda: FakeProvider("{}"))
    registered = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    src = {
        "secret_refs": json.dumps([{"name": REGISTERED_NAME, "ref_id": REGISTERED_REF_ID}]),
        "allowed_spans": "[]",
    }
    assert await worker._leftover_findings(src, f"资料 {registered} 结束") == []

    forged = redactor.private_ref("11010519491231002x-00000000", "pr_0000000000000000")
    assert await worker._leftover_findings(src, f"资料 {forged} 结束") != []


# ---- Wiki 编译：登记引用原样通过，伪造标签删除 ----

async def test_compiler_preserves_registered_reference(settings):
    source_id = _register_source(settings, REGISTERED_NAME, REGISTERED_REF_ID)
    ref = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    plan = {
        "source_summary": {},
        "pages": [{"action": "create", "path": "projects/p.md", "title": "P",
                   "content": f"资料 {ref} 结束"}],
        "conflicts": [],
    }
    provider = FakeProvider(json.dumps({"action": "final", "plan": plan}, ensure_ascii=False))
    await compiler.compile_source(settings, provider, {"id": source_id}, "资料")
    content = (settings.wiki_dir / "projects/p.md").read_text(encoding="utf-8")
    assert ref in content


async def test_compiler_strips_unregistered_reference(settings):
    source_id = _register_source(settings, REGISTERED_NAME, REGISTERED_REF_ID)
    forged = redactor.private_ref("11010519491231002x-00000000", "pr_0000000000000000")
    plan = {
        "source_summary": {},
        "pages": [{"action": "create", "path": "projects/p.md", "title": "P",
                   "content": f"资料 {forged} 结束"}],
        "conflicts": [],
    }
    provider = FakeProvider(json.dumps({"action": "final", "plan": plan}, ensure_ascii=False))
    await compiler.compile_source(settings, provider, {"id": source_id}, "资料")
    content = (settings.wiki_dir / "projects/p.md").read_text(encoding="utf-8")
    assert "11010519491231002x" not in content


def test_compiler_update_preserves_registered_older_source_ref(settings, monkeypatch):
    old_ref = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    db.insert_source(
        sha256_hex("fixture-old"),
        "text",
        "old.txt",
        "",
        json.dumps([{"name": REGISTERED_NAME, "ref_id": REGISTERED_REF_ID}]),
    )
    new_id = db.insert_source(sha256_hex("fixture-new"), "text", "new.txt", "", "[]")
    monkeypatch.setattr(compiler, "rebuild_index", lambda settings: None)
    plan = {
        "pages": [{"action": "update", "path": "entities/example.md", "title": "Example",
                   "content": f"# Example\nExisting info: {old_ref}\nNew fact."}],
    }
    compiler.apply_plan(settings, plan, new_id)
    content = (settings.wiki_dir / "entities/example.md").read_text(encoding="utf-8")
    assert old_ref in content, "updating with a new source stripped an older registered reference"


# ---- 问答输出：登记引用原样通过，伪造标签删除 ----

def _write_page(settings, path, title, content):
    page = settings.wiki_dir / path
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# {title}\n{content}\n", encoding="utf-8")


async def test_answer_preserves_registered_reference(settings):
    _register_source(settings, REGISTERED_NAME, REGISTERED_REF_ID)
    ref = redactor.private_ref(REGISTERED_NAME, REGISTERED_REF_ID)
    _write_page(settings, "projects/demo.md", "Demo", f"资料 {ref}")
    provider = SequenceProvider([
        json.dumps({"action": "read", "path": "projects/demo.md"}),
        json.dumps({"action": "final", "answer": f"根据 [[projects/demo.md|Demo]]：{ref}", "citations": ["projects/demo.md"]}),
    ])
    r = await service.answer(settings, provider, "Demo 是什么")
    assert ref in r["answer"]


async def test_answer_strips_unregistered_reference(settings):
    _register_source(settings, REGISTERED_NAME, REGISTERED_REF_ID)
    forged = redactor.private_ref("11010519491231002x-00000000", "pr_0000000000000000")
    _write_page(settings, "projects/demo.md", "Demo", "资料")
    provider = SequenceProvider([
        json.dumps({"action": "read", "path": "projects/demo.md"}),
        json.dumps({"action": "final", "answer": f"根据 [[projects/demo.md|Demo]]：{forged}", "citations": ["projects/demo.md"]}),
    ])
    r = await service.answer(settings, provider, "Demo 是什么")
    assert "11010519491231002x" not in r["answer"]
