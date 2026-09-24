"""手动维护的名字来自脱敏内容，不让默认文件名淹没意图。"""
import pytest
from tests.test_maintenance_plan_flow import client, SECRET  # noqa: F401
from app import db

@pytest.mark.parametrize('mode', ['confirm', 'default'])
def test_manual_text_uses_short_redacted_filename_without_model_call(client, mode):
    client.patch('/api/settings/security', json={'mode': mode})
    text = '核对重复资源与密码引用。保留来源链接，不要重复建立页面。password=' + SECRET
    r = client.post('/api/ingest', data={'session_id': client.review_session, 'text': text})
    assert r.status_code == 200
    report = client.get('/api/reports', params={'session_id': client.review_session}).json()[0]
    assert report['original_name'] == '核对重复资源与密码引用.txt'
    assert not client.review_model.calls
    assert SECRET not in report['original_name']
    if mode == 'confirm':
        assert r.json()['original_name'] == report['original_name']
    else:
        assert client.get('/api/tasks').json()[0]['original_name'] == report['original_name']


def test_uploaded_txt_keeps_its_filename(client):
    r = client.post('/api/ingest', data={'session_id': client.review_session}, files={'file': ('会议记录.txt', '核对重复资源。'.encode())})
    assert r.status_code == 200
    assert r.json()['original_name'] == '会议记录.txt'


def test_title_removes_private_references_and_limits_length(client):
    r = client.post('/api/ingest', data={'session_id': client.review_session, 'text': 'password='+SECRET+'\n'+'整理知识库资料'*20})
    assert r.status_code == 200
    name = r.json()['original_name']
    assert name != 'pasted.txt' and name.endswith('.txt')
    assert len(name[:-4]) <= 20
    assert all(x not in name for x in (SECRET, 'private:', 'pr_', 'REDACTED', '\n', '/', '\\'))
    assert db.submission_count_waiting() == 1


def test_only_sensitive_text_has_generic_name(client):
    r = client.post('/api/ingest', data={'session_id': client.review_session, 'text': 'password='+SECRET})
    assert r.status_code == 200
    assert r.json()['original_name'] == '对话.txt'
