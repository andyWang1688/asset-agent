import json
from app.wiki import compiler
from app.llm.provider import LLMError


async def test_manifest_and_page_bodies_are_generated_separately(settings):
    class StagedModel:
        def __init__(self): self.calls = []
        async def complete(self, system, user, **kwargs):
            self.calls.append((system, user, kwargs))
            if kwargs.get('json_mode'):
                # Simulate a provider that truncates attempts to produce a whole Wiki in one response.
                if '页面完整 Markdown' in user:
                    raise LLMError('输出过长', code='output_limit')
                return json.dumps({'action': 'final', 'plan': {
                    'source_summary': {'path': 'sources/sample.md', 'title': '资料', 'purpose': '概括来源'},
                    'pages': [{'action': 'create', 'path': 'projects/sample.md', 'title': '项目', 'purpose': '总结项目'}],
                    'conflicts': []}})
            return '# 合成资料\n分步生成的正文。'
    model = StagedModel()
    plan = await compiler.generate_plan(settings, model, '合成资料。' * 3000)
    assert len(model.calls) == 3
    assert plan['plan']['pages'][0]['content'].startswith('# 合成资料')
    assert not (settings.wiki_dir/'projects/sample.md').exists()


async def test_later_page_failure_leaves_wiki_unchanged(settings):
    import pytest
    before = {str(p): p.read_bytes() for p in settings.wiki_dir.rglob('*.md')}
    class Model:
        calls = 0
        async def complete(self, system, user, **kwargs):
            if kwargs.get('json_mode'):
                return json.dumps({'action': 'final', 'plan': {'source_summary': {'path': 'sources/new.md', 'title': '来源'}, 'pages': [{'action': 'create', 'path': 'projects/new.md', 'title': '项目'}], 'conflicts': []}})
            self.calls += 1
            if self.calls == 2:
                raise LLMError('truncated', code='output_limit')
            return '# 完整来源摘要'
    with pytest.raises(LLMError):
        await compiler.generate_plan(settings, Model(), '合成资料')
    assert {str(p): p.read_bytes() for p in settings.wiki_dir.rglob('*.md')} == before


async def test_page_writer_receives_existing_facts_and_source_links(settings):
    page = settings.wiki_dir/'projects/existing.md'
    page.write_text('# 项目\n必须保留的旧事实。')
    class Model:
        reads = 0
        writes = []
        async def complete(self, system, user, **kwargs):
            if kwargs.get('json_mode'):
                self.reads += 1
                if self.reads == 1:
                    return json.dumps({'action': 'read', 'path': 'projects/existing.md'})
                return json.dumps({'action': 'final', 'plan': {'source_summary': {'path': 'sources/new.md', 'title': '来源'}, 'pages': [{'action': 'update', 'path': 'projects/existing.md', 'title': '项目'}], 'conflicts': []}})
            self.writes.append(user)
            return '# 项目\n必须保留的旧事实。\n新事实。'
    model = Model()
    await compiler.generate_plan(settings, model, '新事实。')
    assert '必须保留的旧事实' in model.writes[1]
    assert 'sources/new.md' in model.writes[1]
    assert page.read_text() == '# 项目\n必须保留的旧事实。'
