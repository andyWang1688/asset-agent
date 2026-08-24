import json

from app import db
from app.wiki import compiler
from tests.fakes import FakeProvider

PLAN = {
    "source_summary": {
        "title": "测试来源",
        "path": "sources/2026-08-15-test.md",
        "content": "# 测试来源\n\n> 来源：测试\n\n介绍 [[projects/demo-project.md|Demo 项目]]。\n",
    },
    "pages": [
        {
            "action": "create",
            "path": "projects/demo-project.md",
            "title": "Demo 项目",
            "content": "# Demo 项目\n\n> 来源：[[sources/2026-08-15-test.md|测试来源]]\n\nDemo 项目介绍。\n",
        }
    ],
    "conflicts": [],
}


async def test_compile_creates_pages_index_log(settings):
    provider = FakeProvider(json.dumps(PLAN, ensure_ascii=False))
    src = {"id": 1}
    result = await compiler.compile_source(settings, provider, src, "项目 Demo 的资料")
    assert "sources/2026-08-15-test.md" in result["changes"]
    assert (settings.wiki_dir / "projects/demo-project.md").exists()
    index = (settings.wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Demo 项目" in index
    log = (settings.wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "#1" in log
    assert any(r["path"] == "projects/demo-project.md" for r in db.list_pages())


async def test_compile_update_no_duplicate(settings):
    provider = FakeProvider(json.dumps(PLAN, ensure_ascii=False))
    await compiler.compile_source(settings, provider, {"id": 1}, "第一次资料")
    await compiler.compile_source(settings, provider, {"id": 2}, "第二次资料")
    files = list((settings.wiki_dir / "projects").glob("*.md"))
    assert [f.name for f in files] == ["demo-project.md"]
    assert len(db.list_pages()) == 2  # 来源页 + 项目页


async def test_compile_blocks_illegal_path(settings):
    bad = dict(PLAN)
    bad["pages"] = [{"action": "create", "path": "../../etc/passwd.md", "title": "x", "content": "x"}]
    provider = FakeProvider(json.dumps(bad, ensure_ascii=False))
    try:
        await compiler.compile_source(settings, provider, {"id": 1}, "资料")
        assert False
    except ValueError:
        pass


async def test_compile_strips_secret_from_llm_output(settings):
    bad = dict(PLAN)
    bad["pages"][0]["content"] = "# Demo\n\npassword=Sup3rSecret! 不应出现\n"
    provider = FakeProvider(json.dumps(bad, ensure_ascii=False))
    await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    content = (settings.wiki_dir / "projects/demo-project.md").read_text(encoding="utf-8")
    assert "Sup3rSecret!" not in content
    assert any(e["kind"] == "llm_output_secret" for e in db.list_security())


async def test_compile_strips_secret_from_title_and_conflict_note(settings):
    bad = dict(PLAN)
    bad["pages"][0]["title"] = "Demo password=Sup3rSecret!"
    bad["conflicts"] = [{"between": ["a.md", "b.md"], "note": "冲突 token=sk-proj-abcdEFGH12345678901234567890 说明"}]
    provider = FakeProvider(json.dumps(bad, ensure_ascii=False))
    await compiler.compile_source(settings, provider, {"id": 1}, "资料")
    content = (settings.wiki_dir / "projects/demo-project.md").read_text(encoding="utf-8")
    assert "Sup3rSecret!" not in content
    log = (settings.wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "sk-proj" not in log
