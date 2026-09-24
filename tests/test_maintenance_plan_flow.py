"""确认报告的真实 API 流程；模型与保险柜为内存替身，资料完全虚构。"""
import json
import pytest
from fastapi.testclient import TestClient
import app.main as main
from app import db
from tests.fakes import FakeCredentialStore

SECRET = 'PlanFixtureSecret42!'
PLAN = {'source_summary': {'path': 'sources/plan.md', 'title': '读书安排', 'content': '# 读书安排\n周二九点半。'},
        'pages': [{'action': 'create', 'path': 'projects/reading.md', 'title': '读书会', 'content': '# 读书会\n周二九点半。'}], 'conflicts': []}

class PlanningModel:
    def __init__(self): self.calls=[]
    async def complete(self, system, user, **kwargs):
        assert SECRET not in system + user
        assert kwargs["max_tokens"] == 16000
        self.calls.append(user)
        return json.dumps({'action': 'final', 'plan': PLAN}, ensure_ascii=False)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE_DIR', str(tmp_path/'ws'))
    monkeypatch.setenv('DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('POLICY_FILE', str(tmp_path/'policy.yaml'))
    monkeypatch.delenv('LOCAL_KEY_FILE', raising=False)
    vault = FakeCredentialStore(); model = PlanningModel()
    monkeypatch.setattr(main, 'VaultwardenAdapter', lambda _:vault)
    monkeypatch.setattr(main, 'get_active_provider', lambda _:model)
    monkeypatch.setattr(main, 'get_security_provider', lambda _:None)
    monkeypatch.setattr(main.Worker, 'start', lambda _:None)
    with TestClient(main.app) as c:
        c.patch('/api/settings/security',json={'mode':'confirm'})
        sid=c.post('/api/chat/sessions',json={'mode':'maintain'}).json()['session_id']
        c.review_session=sid; c.review_vault=vault; c.review_model=model
        yield c


def submit(client):
    r=client.post('/api/ingest',data={'text':'读书会周二九点半开始。password='+SECRET,'session_id':client.review_session})
    assert r.status_code==200
    view=r.json()
    body={'session_id':client.review_session,'decisions':{f['id']:'store' for f in view['findings']},'edits':{}}
    return view['submission_id'],body


def finish(client, sid, body):
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    assert r.status_code == 202, r.text
    tid = r.json()['task_id']
    client.portal.call(main.app.state.ctx.worker.tick)
    task = db.get_task(tid)
    assert task['status'] == 'done', task['error']
    return {'task_id': tid, 'source_id': task['source_id']}


def test_editable_draft_is_locked_after_single_confirmation(client):
    sid, body = submit(client)
    fid = next(iter(body['decisions']))
    body['edits'] = {fid: {'name': '读书账号'}}
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    assert r.status_code == 202
    assert not client.review_model.calls and not client.review_vault.created
    assert client.post(f'/api/pending/submissions/{sid}/review', json=body).status_code == 400
    assert client.post(f'/api/pending/submissions/{sid}/cancel').status_code == 400
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(r.json()['task_id'])['status'] == 'done'
    assert client.review_vault.created[0].name == '读书账号'
    assert db.get_submission(sid)['payload'] == ''


def test_unhandled_secret_fails_task_without_model_call(client):
    sid, body = submit(client)
    body['edited_text'] = 'new password=NewUnconfirmedSecret42!'
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    assert r.status_code == 202
    client.portal.call(main.app.state.ctx.worker.tick)
    task = db.get_task(r.json()['task_id'])
    assert task['status'] == 'failed'
    assert not client.review_model.calls and not client.review_vault.created
    assert not db.list_sources()
    assert db.get_submission(sid)['payload'] == ''


def test_policy_change_after_acceptance_fails_task(client):
    sid, body = submit(client)
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    client.patch('/api/settings/security', json={'mode': 'default'})
    client.portal.call(main.app.state.ctx.worker.tick)
    task = db.get_task(r.json()['task_id'])
    assert task['status'] == 'failed' and '安全策略' in task['error']
    assert not client.review_model.calls and not client.review_vault.created


def test_reject_before_acceptance_has_no_task(client):
    sid, body = submit(client)
    assert client.post(f'/api/pending/submissions/{sid}/cancel').status_code == 200
    assert client.post(f'/api/pending/submissions/{sid}/confirm', json=body).status_code == 400
    assert not db.list_tasks() and db.get_submission(sid)['payload'] == ''


def test_acceptance_is_bound_to_session(client):
    sid, body = submit(client)
    other = client.post('/api/chat/sessions', json={'mode': 'maintain'}).json()['session_id']
    assert client.post(f'/api/pending/submissions/{sid}/confirm', json={**body, 'session_id': other}).status_code == 400
    assert not db.list_tasks()


def test_failed_model_is_a_terminal_task_not_another_review(client):
    import httpx
    class TimeoutModel:
        async def complete(self, *args, **kwargs):
            raise httpx.ReadTimeout('password=SensitiveUpstreamMessage!')
    main.app.state.ctx.worker.get_provider = lambda: TimeoutModel()
    sid, body = submit(client)
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    client.portal.call(main.app.state.ctx.worker.tick)
    task = client.get('/api/tasks').json()[0]
    assert task['id'] == r.json()['task_id'] and task['status'] == 'failed'
    assert '超时' in task['error'] and 'SensitiveUpstreamMessage' not in json.dumps(task)
    assert not client.review_vault.created and not db.list_sources()
    assert db.get_submission(sid)['payload'] == ''
    assert all(r['status'] != 'waiting' for r in client.get('/api/pending/submissions').json())
    assert client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id'] == task['id']
    assert len(db.list_tasks()) == 1


def test_restart_fails_interrupted_tasks_but_keeps_queued_work(client):
    from app.security import plans
    sid, body = submit(client)
    tid = client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id']
    plans.recover_interrupted()
    assert db.get_task(tid)['status'] == 'planning_pending'
    db.update_task_status(tid, 'planning')
    plans.recover_interrupted()
    assert db.get_task(tid)['status'] == 'failed'
    assert db.get_submission(sid)['payload'] == ''


def test_old_plan_endpoint_cannot_silently_authorize_execution(client):
    sid, body = submit(client)
    assert client.post(f'/api/pending/submissions/{sid}/plan', json=body).status_code == 410
    assert not db.list_tasks() and not client.review_model.calls


@pytest.mark.parametrize('field', ['path', 'conflict'])
def test_model_plan_metadata_cannot_expose_unscanned_secret(client, field):
    class UnsafePlanModel:
        async def complete(self, *args, **kwargs):
            plan = json.loads(json.dumps(PLAN))
            if field == 'path':
                plan['pages'][0]['path'] = 'projects/password=PlanOutputSecret42!.md'
            else:
                plan['conflicts'] = [{'between': ['password=PlanOutputSecret42!'], 'note': '存在冲突'}]
            return json.dumps({'action': 'final', 'plan': plan})
    main.app.state.ctx.worker.get_provider = lambda: UnsafePlanModel()
    sid, body = submit(client)
    client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert 'PlanOutputSecret42!' not in client.get('/api/tasks').text
    assert 'PlanOutputSecret42!' not in client.get('/api/reports').text
