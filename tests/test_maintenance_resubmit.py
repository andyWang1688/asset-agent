"""重用来源不重用任务，保护旧 Raw、旧报告以及每轮的整理要求。"""
import json
from pathlib import Path
import pytest
from app import db
from app.ingest import receiver
from app.security.policy import PolicyStore
from app.worker import Worker
from tests.fakes import FakeCredentialStore, FakeProvider, ingest_and_finish, finish_queued

async def submit(settings, vault, session, instruction):
    PolicyStore(settings.policy_file).update_security_settings({'mode':'default'})
    return await ingest_and_finish(settings,vault,filename='notes.md',data=b'password=RoundSecret42! notes',
        instruction=instruction,session_id=session,knowledge_provider_getter=lambda:FakeProvider('{}'))

async def test_repeated_file_uses_immutable_raw_and_new_task_instruction(settings, maintain_session, monkeypatch):
    vault=FakeCredentialStore()
    first=await submit(settings,vault,maintain_session,'第一次按项目整理')
    original=dict(db.get_source(first['source_id']))
    raw=Path(original['path']).read_bytes()
    db.update_task_status(first['task_id'],'done')
    second=await submit(settings,vault,maintain_session,'第二次补充分析')
    assert first['source_id']==second['source_id']
    assert first['task_id']!=second['task_id'] and first['report_id']!=second['report_id']
    assert len(vault.created)==1
    assert dict(db.get_source(first['source_id']))==original
    assert Path(original['path']).read_bytes()==raw
    assert db.report_view(first['report_id'])['instruction']=='第一次按项目整理'
    snapshot=json.loads(db.get_task(second['task_id'])['input_snapshot'])
    assert snapshot['instruction']=='第二次补充分析'
    assert 'RoundSecret42!' not in snapshot['text']
    assert db.get_task(second['task_id'])['status']=='done'

async def test_failed_manual_input_can_start_new_round_without_duplicate_vault(settings, maintain_session):
    vault=FakeCredentialStore();PolicyStore(settings.policy_file).update_security_settings({'mode':'default'})
    async def add():
        return await receiver.ingest(settings,vault,text='password=RetrySecret42! 读书会资料',
            session_id=maintain_session,knowledge_provider_getter=lambda:FakeProvider('{}'))
    first=await add()
    await Worker(settings,vault,lambda:FakeProvider('{}'),lambda:None).tick()
    assert not db.list_sources() and not vault.created
    second=await finish_queued(settings,vault,await add())
    assert second['task_id']!=first['task_id'] and second['report_id']!=first['report_id']
    assert db.get_task(first['task_id'])['status']=='failed'
    assert len(vault.created)==1

async def test_different_instruction_secrets_do_not_alias_private_references(settings, maintain_session):
    vault=FakeCredentialStore()
    first=await submit(settings,vault,maintain_session,'password=FirstSecret42!')
    second=await submit(settings,vault,maintain_session,'password=OtherSecret42!')
    one=db.report_view(first['report_id']);two=db.report_view(second['report_id'])
    a=next(e for e in one['entries'] if e['source']=='整理要求')
    b=next(e for e in two['entries'] if e['source']=='整理要求')
    assert a['ref_id']!=b['ref_id']
    assert a['vault']['item_id']!=b['vault']['item_id']
    assert 'FirstSecret42!' not in json.dumps(one) and 'OtherSecret42!' not in json.dumps(two)
