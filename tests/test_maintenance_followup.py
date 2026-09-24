"""连续维护必须有同会话上下文，反复搜索不能重复占用正文预算。"""
import json
import pytest
from app import db
from app.wiki.tools import WikiTools, ToolBudgetExceeded
from app.wiki import compiler
from app.security.policy import PolicyStore
from tests.test_maintenance_plan_flow import client, submit  # noqa: F401
import app.main as main


def test_repeated_search_reuses_content_already_in_context(settings):
    page=settings.wiki_dir/'entities/fixture.md'; page.write_text('# 读书项目\n'+'读书笔记。'*100)
    tools=WikiTools(settings,max_read_chars=800)
    first=tools.search('读书')
    used=tools.used_chars
    assert first['results'][0]['content']
    second=tools.search('笔记')
    assert second['results'][0]['already_read'] is True
    assert 'content' not in second['results'][0]
    assert tools.read_page('entities/fixture.md')['already_read'] is True
    assert tools.used_chars==used
    assert tools.read_pages=={'entities/fixture.md'}


def test_changed_page_is_not_silently_reused(settings):
    page=settings.wiki_dir/'entities/fixture.md';page.write_text('# 读书\n旧事实')
    tools=WikiTools(settings)
    tools.read_page('entities/fixture.md')
    page.write_text('# 读书\n新事实')
    assert '新事实' in tools.read_page('entities/fixture.md')['content']


def test_new_content_still_obeys_budget(settings):
    (settings.wiki_dir/'entities/fixture.md').write_text('# 读书\n'+'读书笔记。'*100)
    with pytest.raises(ToolBudgetExceeded):
        WikiTools(settings,max_read_chars=10).search('读书')


@pytest.mark.parametrize("mode", ["confirm", "default"])
def test_followup_receives_same_session_result_without_secrets(client, mode):
    settings=main.app.state.ctx.settings
    def previous(session, note, preview):
        rid=db.insert_report(session,None,'confirmed','confirm','text','对话.txt','fixture-'+session,'{}','[]',preview)
        tid=db.insert_task(None,session_id=session,report_id=rid)
        db.set_task_result(tid,json.dumps({'changes':['entities/fixture.md'],'conflicts':[{'note':note,'between':['entities/fixture.md']}]}))
        db.update_task_status(tid,'done')
    (settings.wiki_dir/'entities/fixture.md').write_text('# 读书\n旧事实')
    previous(client.review_session,'同一书目重复记录需要核对','password=HistoryFixtureSecret42!')
    db.create_session('another-session','maintain')
    previous('another-session','OTHER_SESSION_MUST_NOT_APPEAR','其他资料')
    class Model:
        async def complete(self, system, user, **kwargs):
            assert '同一书目重复记录需要核对' in user
            assert 'HistoryFixtureSecret42!' not in user
            assert 'OTHER_SESSION_MUST_NOT_APPEAR' not in user
            return json.dumps({'action':'final','plan':{'source_summary':{'path':'sources/followup.md','title':'核对','content':'# 核对\n已经处理。'}}})
    model=Model();main.app.state.ctx.worker.get_provider=lambda:model
    if mode == 'confirm':
        sid,body=submit(client)
        r=client.post(f'/api/pending/submissions/{sid}/confirm',json=body)
    else:
        client.patch('/api/settings/security', json={'mode':'default'})
        r=client.post('/api/ingest', data={'session_id':client.review_session,'text':'请处理上次提到的重复记录。'})
    client.portal.call(main.app.state.ctx.worker.tick)
    task=db.get_task(r.json()['task_id'])
    assert task['status']=='done', task['error']


def test_context_excludes_unaccepted_and_future_tasks(settings):
    db.create_session('maintain', 'maintain')
    for status in ['pending', 'rejected', 'confirmed']:
        rid=db.insert_report('maintain',None,status,'confirm','text','fixture.txt',status,'{}','[]','DO_NOT_SEND_'+status)
        tid=db.insert_task(None,session_id='maintain',report_id=rid)
        db.update_task_status(tid,'done')
    context=compiler.maintenance_context(settings,'maintain',tid)
    assert 'DO_NOT_SEND' not in context
