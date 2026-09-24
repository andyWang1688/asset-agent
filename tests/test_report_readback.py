"""任务回看只保存用户裁决后的结构，不重新读取上传原件。"""
import json
from io import BytesIO

import pytest
from openpyxl import Workbook

from app import db
import app.main as main
from tests.test_maintenance_plan_flow import client, submit, SECRET  # noqa: F401
from tests.document_samples import sample_file


def confirm(client, sid, body):
    r = client.post(f'/api/pending/submissions/{sid}/confirm', json=body)
    assert r.status_code == 202
    return r.json()


def readback(client, receipt):
    r = client.get(f"/api/reports/{receipt['report_id']}")
    assert r.status_code == 200
    return r.json()['review_snapshot']


def test_snapshot_immediate_immutable_and_survives_payload_destruction(client):
    sid, body = submit(client)
    fid = next(iter(body['decisions']))
    body['edits'] = {fid: {'name': '读书服务密码'}}
    receipt = confirm(client, sid, body)
    snapshot = readback(client, receipt)
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert SECRET not in encoded and '读书服务密码' in encoded
    assert 'text' not in snapshot['documents'][0]
    assert all('text' not in u for u in snapshot['documents'][0]['units'])
    assert not client.review_model.calls and not client.review_vault.created
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(receipt['task_id'])['status'] == 'done'
    assert db.get_submission(sid)['payload'] == ''
    assert readback(client, receipt) == snapshot
    assert client.post(f'/api/pending/submissions/{sid}/review', json=body).status_code == 400


def test_snapshot_survives_model_failure(client):
    class Broken:
        async def complete(self, *args, **kwargs):
            raise ValueError('fixture')
    main.app.state.ctx.worker.get_provider = lambda: Broken()
    sid, body = submit(client)
    receipt = confirm(client, sid, body)
    snapshot = readback(client, receipt)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(receipt['task_id'])['status'] == 'failed'
    assert db.get_submission(sid)['payload'] == ''
    assert readback(client, receipt) == snapshot


def test_snapshot_preserves_sheets_manual_protection_and_allow(client):
    book = Workbook(); book.active.title = '账号'
    book.active.append(['服务', '密码']); book.active.append(['青竹', SECRET])
    book.create_sheet('私人地址').append(['说明'])
    book['私人地址'].append(['家中'])
    buf = BytesIO(); book.save(buf)
    v = client.post('/api/ingest', data={'session_id': client.review_session},
                    files={'file': ('fixture.xlsx', buf.getvalue())}).json()
    sid = v['submission_id']
    body = {'session_id': client.review_session, 'decisions': {f['id']: 'allow' for f in v['findings']}}
    review = client.post(f'/api/pending/submissions/{sid}/review', json=body).json()
    doc = review['documents'][0]
    selected = [u for u in doc['units'] if u['text'] in ('青竹', '私人地址')]
    body['manual'] = [{'source': 'document', 'start': u['start'], 'end': u['end']} for u in selected]
    body['edits'] = {}
    for mark in body['manual']:
        fid = f"manual:document:{mark['start']}:{mark['end']}"
        body['decisions'][fid] = 'store'
        body['edits'][fid] = {'name': '个人资料'}
    receipt = confirm(client, sid, body)
    snapshot = readback(client, receipt)
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert '私人地址' not in encoded and '青竹' not in encoded
    # 用户明确放行的值按原样回看，不能套用提交时默认保护结果。
    assert SECRET in encoded
    doc = snapshot['documents'][0]
    assert len(doc['sheets']) == 2
    assert any(u['row'] == 2 and u['col'] == 2 and u['preview'] == SECRET for u in doc['units'])
    assert any(u['preview_spans'] for u in doc['units'])


@pytest.mark.parametrize('ext', ['txt', 'docx', 'pdf'])
def test_text_documents_have_readback_without_original_files(client, ext):
    v = client.post('/api/ingest', data={'session_id': client.review_session},
                    files={'file': ('sample.' + ext, (b'plain fixture' if ext == 'txt' else sample_file(ext)))}).json()
    receipt = confirm(client, v['submission_id'], {'session_id': client.review_session,
                       'decisions': {f['id']: f['suggested_action'] for f in v['findings']}})
    doc = readback(client, receipt)['documents'][0]
    assert doc['units'] and not doc['sheets']
    assert all('text' not in u for u in doc['units'])


def test_auto_mode_preserves_structured_readback(client):
    client.patch('/api/settings/security', json={'mode': 'default'})
    r = client.post('/api/ingest', data={'session_id': client.review_session},
                    files={'file': ('sample.xlsx', sample_file('xlsx'))})
    assert r.status_code == 200
    snapshot = readback(client, r.json())
    assert snapshot['documents'][0]['sheets']


def test_unscanned_edited_text_never_enters_snapshot(client):
    sid, body = submit(client)
    body['edited_text'] = 'password=NewUnconfirmedSecret42!'
    receipt = confirm(client, sid, body)
    assert readback(client, receipt) == {}
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(receipt['task_id'])['status'] == 'failed'
    report = client.get(f"/api/reports/{receipt['report_id']}").json()
    assert 'NewUnconfirmedSecret42!' not in json.dumps(report)
