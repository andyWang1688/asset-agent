"""区分计划协议错误与安全复扫失败，不泄露模型输出或数据。"""
import json
import pytest
from app import db
from app.wiki import compiler
from app.security import plans
from app.ingest.finalize import GateBlockedError
from tests.test_maintenance_plan_flow import client, submit  # noqa: F401
import app.main as main


def test_missing_read_is_not_reported_as_a_security_failure(client):
    page = main.app.state.ctx.settings.wiki_dir/'entities/fixture.md'
    page.write_text('# 项目\n旧事实必须保留。')
    class Model:
        async def complete(self, *args, **kwargs):
            return json.dumps({'action':'final','plan':{'pages':[{'action':'update','path':'entities/fixture.md','title':'项目','content':'新正文'}]}})
    main.app.state.ctx.worker.get_provider=lambda: Model()
    sid, body=submit(client)
    r=client.post(f'/api/pending/submissions/{sid}/confirm',json=body)
    client.portal.call(main.app.state.ctx.worker.tick)
    task=db.get_task(r.json()['task_id'])
    assert task['status']=='failed'
    assert '未读取' in task['error'] and '安全检查' not in task['error']
    assert page.read_text()=='# 项目\n旧事实必须保留。'
    assert not client.review_vault.created and not db.list_sources()


def test_rescan_failure_is_distinct_and_never_echoes_rule_text():
    message=plans.failure_message(GateBlockedError('fixture-secret-private-value'))
    assert '敏感内容' in message and '计划' not in message
    assert 'fixture-secret' not in message


async def test_invalid_action_has_safe_specific_reason(settings):
    class Model:
        async def complete(self, *args, **kwargs):
            return json.dumps({'action':'final','plan':{'pages':[{'action':'fixture-secret-private-value','path':'entities/sample.md','title':'项目'}]}})
    with pytest.raises(ValueError) as caught:
        await compiler.generate_plan(settings,Model(),'修改资料')
    message=plans.failure_message(caught.value)
    assert '操作' in message and '安全检查' not in message
    assert 'fixture-secret' not in message


def test_read_budget_and_reasoning_only_have_specific_messages():
    from app.wiki.tools import ToolBudgetExceeded
    from app.llm.provider import LLMError
    assert '容量限制' in plans.failure_message(ToolBudgetExceeded('do-not-show'))
    assert '推理过程' in plans.failure_message(LLMError('do-not-show', code='reasoning_only'))
