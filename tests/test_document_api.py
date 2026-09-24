import pytest
from fastapi.testclient import TestClient

from app import db
import app.main as main
from app.security.policy import PolicyStore
from tests.document_samples import sample_file
from tests.fakes import FakeCredentialStore, FakeProvider


@pytest.fixture
def document_client(settings, monkeypatch):
    provider = FakeProvider('{}')
    creds = FakeCredentialStore()
    monkeypatch.setattr(main, 'VaultwardenAdapter', lambda _: creds)
    monkeypatch.setattr(main, 'get_active_provider', lambda _: provider)
    PolicyStore(settings.policy_file).update_security_settings({'mode': 'confirm'})
    with TestClient(main.app) as client:
        yield client, provider, creds


@pytest.mark.parametrize('extension', ['xlsx', 'xls', 'docx', 'pdf', 'csv'])
def test_multipart_file_reaches_confirmation(document_client, extension):
    client, provider, creds = document_client
    sid = client.post('/api/chat/sessions', json={'mode': 'maintain'}).json()['session_id']
    response = client.post('/api/ingest', data={'session_id': sid},
                           files={'file': (f'资料.{extension}', sample_file(extension))})
    assert response.status_code == 200
    assert response.json()['pending_confirmation'] is True
    assert 'DocImport9!' not in response.text
    assert db.list_tasks() == [] and db.list_sources() == []
    assert provider.calls == [] and creds.created == []


def test_invalid_document_is_400_without_side_effects(document_client):
    client, provider, creds = document_client
    sid = client.post('/api/chat/sessions', json={'mode': 'maintain'}).json()['session_id']
    response = client.post('/api/ingest', data={'session_id': sid},
                           files={'file': ('a.docx', b'password=NeverEcho9!')})
    assert response.status_code == 400
    assert '文件解析失败' in response.json()['detail']
    assert 'NeverEcho9!' not in response.text
    assert db.list_tasks() == [] and db.list_sources() == [] and db.list_submissions() == []
    assert provider.calls == [] and creds.created == []


def test_ask_session_cannot_upload_office_document(document_client):
    client, provider, creds = document_client
    sid = client.post('/api/chat/sessions', json={'mode': 'ask'}).json()['session_id']
    response = client.post('/api/ingest', data={'session_id': sid},
                           files={'file': ('a.xlsx', sample_file('xlsx'))})
    assert response.status_code == 400
    assert '仅维护会话' in response.json()['detail']
    assert db.list_tasks() == [] and db.list_submissions() == []
    assert provider.calls == [] and creds.created == []
