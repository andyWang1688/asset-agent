"""审查确认即创建任务；生成计划是后台阶段，不再二次确认。"""
import json
from app import db
import app.main as main
from tests.test_maintenance_plan_flow import client, submit  # noqa: F401


def test_confirmation_immediately_creates_one_task_without_model_call(client):
    sid, body = submit(client)
    response = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    assert response.status_code == 202
    task_id = response.json()['task_id']
    tasks = client.get('/api/tasks').json()
    assert len(tasks) == 1 and tasks[0]['id'] == task_id
    assert tasks[0]['status'] == 'planning_pending'
    assert tasks[0]['original_name']
    assert not client.review_model.calls and not client.review_vault.created
    assert client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id'] == task_id
    assert client.post(f'/api/pending/submissions/{sid}/cancel').status_code == 400
    client.portal.call(main.app.state.ctx.worker.tick)
    assert len(db.list_tasks()) == 1
    assert db.get_task(task_id)['status'] == 'done'
    assert db.get_submission(sid)['payload'] == ''
    assert client.review_vault.created


def test_slow_plan_has_visible_task_and_locked_review(client):
    import asyncio
    from tests.test_maintenance_plan_flow import PlanningModel
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class SlowModel(PlanningModel):
            async def complete(self, *args, **kwargs):
                started.set()
                await release.wait()
                return await super().complete(*args, **kwargs)
        main.app.state.ctx.worker.get_provider = lambda: SlowModel()
        sid, body = submit(client)
        tid = client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id']
        job = asyncio.create_task(main.app.state.ctx.worker.tick())
        await asyncio.wait_for(started.wait(), 2)
        assert client.get('/api/tasks').json()[0]['status'] == 'planning'
        assert client.get('/api/health').status_code == 200
        assert client.post(f'/api/pending/submissions/{sid}/cancel').status_code == 400
        assert client.post(f'/api/pending/submissions/{sid}/review', json=body).status_code == 400
        assert not client.review_vault.created
        release.set()
        await job
        assert db.get_task(tid)['status'] == 'done' and len(db.list_tasks()) == 1
    asyncio.run(scenario())


def test_deleting_conversation_does_not_cancel_accepted_task(client):
    sid, body = submit(client)
    tid = client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id']
    db.delete_session(client.review_session)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done'
