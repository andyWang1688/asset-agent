"""1.0 发布门槛：临时目录、合成资料、真实 API / Worker，模型与保险柜隔离。"""
import json
import pytest
import app.main as main
from app import db
from app.wiki import compiler
from tests.test_maintenance_plan_flow import client, SECRET, submit  # noqa: F401


def upload(client, files=None):
    files = files or [('one.txt', ('password=' + SECRET).encode()), ('two.txt', '周二读书'.encode())]
    r = client.post('/api/ingest', data={'session_id': client.review_session},
                    files=[('files', (name, content, 'application/octet-stream')) for name, content in files])
    assert r.status_code == 200, r.text
    return r.json()


def accept(client, view):
    r = client.post(f"/api/pending/submissions/{view['submission_id']}/confirm", json={
        'session_id': client.review_session, 'decisions': {f['id']: 'store' for f in view['findings']}})
    assert r.status_code == 202, r.text
    return r.json()['task_id']


def test_batch_archives_exact_originals_and_creates_one_task(client):
    view = upload(client)
    s = main.app.state.ctx.settings
    assert not list(s.private_raw_dir.rglob('*.txt'))
    review = client.post(f"/api/pending/submissions/{view['submission_id']}/review", json={'session_id': client.review_session}).json()
    assert [d['name'] for d in review['documents']] == ['one.txt', 'two.txt']
    tid = accept(client, view)
    assert len(db.list_tasks()) == 1
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done', db.get_task(tid)['error']
    assert len(db.sources_for_task(tid)) == 2
    originals = [p.read_bytes() for p in s.private_raw_dir.rglob('*') if p.is_file()]
    assert sorted(originals) == sorted([('password=' + SECRET).encode(), '周二读书'.encode()])
    assert all(SECRET not in p.read_text() for p in s.raw_dir.rglob('*') if p.is_file())
    assert not list((s.data_dir / 'transactions').glob('*.json'))


def test_invalid_file_rejects_entire_batch(client):
    r = client.post('/api/ingest', data={'session_id': client.review_session}, files=[
        ('files', ('one.txt', b'hello')), ('files', ('bad.pdf', b'broken'))])
    assert r.status_code == 400
    assert not db.list_tasks() and not db.list_submissions('waiting') and not db.list_sources()


def test_rejected_upload_and_manual_text_do_not_archive(client):
    view = upload(client)
    client.post(f"/api/pending/submissions/{view['submission_id']}/cancel")
    sid, body = submit(client)
    tid = client.post(f'/api/pending/submissions/{sid}/confirm', json=body).json()['task_id']
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done'
    assert not [p for p in main.app.state.ctx.settings.private_raw_dir.rglob('*') if p.is_file()]


@pytest.mark.parametrize('point', ['vault', 'wiki', 'index', 'raw'])
def test_failure_rolls_back_batch(client, monkeypatch, point):
    s = main.app.state.ctx.settings
    old = s.wiki_dir / 'concepts/keep.md'; old.write_text('# 保留\n旧内容')
    compiler.rebuild_index(s)
    before = {str(p): p.read_bytes() for p in s.wiki_dir.rglob('*.md')}
    pages = [dict(r) for r in db.list_pages()]
    deleted = []
    async def delete(ref): deleted.append(ref.item_id)
    monkeypatch.setattr(client.review_vault, 'delete_secret', delete)
    def fail(*args, **kwargs): raise OSError('fixture failure')
    if point == 'vault':
        original = client.review_vault.create_secret
        async def fail_second(payload):
            if client.review_vault.created: raise RuntimeError('fixture vault failure')
            return await original(payload)
        monkeypatch.setattr(client.review_vault, 'create_secret', fail_second)
    elif point == 'wiki':
        original = compiler._write_page
        def partial(*args):
            original(*args)
            fail()
        monkeypatch.setattr(compiler, '_write_page', partial)
    elif point == 'index': monkeypatch.setattr(compiler, 'rebuild_index', fail)
    else:
        from app.ingest import transaction
        monkeypatch.setattr(transaction.Transaction, 'write_raw', fail)
    view = upload(client, [('one.txt', ('password='+SECRET).encode()), ('two.txt', b'password=AnotherFixtureSecret42!')])
    tid = accept(client, view)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'failed'
    assert len(deleted) == len(client.review_vault.created)
    assert not db.list_sources() and not db.sources_for_task(tid)
    assert {str(p): p.read_bytes() for p in s.wiki_dir.rglob('*.md')} == before
    assert [dict(r) for r in db.list_pages()] == pages
    assert not [p for p in s.raw_dir.rglob('*') if p.is_file()]
    assert not [p for p in s.private_raw_dir.rglob('*') if p.is_file()]


def test_auto_mode_is_same_background_task(client):
    client.patch('/api/settings/security', json={'mode': 'default'})
    view = upload(client)
    assert not view.get('pending_confirmation') and view['task_id']
    assert not client.review_model.calls and not client.review_vault.created
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(view['task_id'])['status'] == 'done'
    assert len(db.sources_for_task(view['task_id'])) == 2


@pytest.mark.parametrize('extension', ['xlsx', 'xls', 'docx', 'pdf', 'csv'])
def test_mixed_formats_preserve_bytes_and_review_coordinates(client, extension):
    from tests.document_samples import sample_file
    content = sample_file(extension)
    view = upload(client, [('first.txt', b'ordinary first'), (f'second.{extension}', content)])
    review = client.post(f"/api/pending/submissions/{view['submission_id']}/review", json={'session_id': client.review_session}).json()
    doc = review['documents'][1]
    assert doc['name'] == f'second.{extension}'
    unit = next(u for u in doc['units'] if 'DocImport9!' in u['text'])
    assert unit['start'] > len('ordinary first')
    tid = accept(client, view)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done', db.get_task(tid)['error']
    paths = [p for p in main.app.state.ctx.settings.private_raw_dir.rglob('*') if p.is_file()]
    assert any(p.read_bytes() == content for p in paths)
    assert all('DocImport9!' not in call for call in client.review_model.calls)
    refs = db.report_view(view['report_id'])['entries']
    for entry in refs:
        meta = db.find_ref_metadata(entry['ref_id'])
        assert meta and meta['private_path'] and meta['location']
        assert client.get('/api/private_raw/' + str(meta['private_path'])).status_code == 404


def test_manual_mark_in_second_file_and_same_filename(client):
    view = upload(client, [('same.txt', b'first sentence'), ('same.txt', b'second sentence')])
    body = {'session_id': client.review_session}
    endpoint = f"/api/pending/submissions/{view['submission_id']}"
    docs = client.post(endpoint + '/review', json=body).json()['documents']
    unit = docs[1]['units'][0]
    fid = f"manual:{docs[1]['id']}:{unit['start']}:{unit['end']}"
    body.update(manual=[{'source': docs[1]['id'], 'start': unit['start'], 'end': unit['end']}], decisions={fid: 'store'})
    review = client.post(endpoint + '/review', json=body)
    assert review.status_code == 200
    assert 'second sentence' not in review.json()['documents'][1]['preview']
    tid = client.post(endpoint + '/confirm', json=body).json()['task_id']
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done'
    assert len(db.sources_for_task(tid)) == 2 and len(db.list_sources()) == 2
    originals = [p.read_bytes() for p in main.app.state.ctx.settings.private_raw_dir.rglob('*') if p.is_file()]
    assert sorted(originals) == [b'first sentence', b'second sentence']


def test_restart_recovers_uncommitted_files_and_database(client):
    from app.ingest.transaction import Transaction, recover
    s = main.app.state.ctx.settings
    tid = accept(client, upload(client))
    db.update_task_status(tid, 'saving')
    tx = Transaction(s, client.review_vault, tid)
    tx.archive('original.txt', b'fixture original', 0)
    tx.write_raw(s.inbox_dir / 'new.md', 'safe fixture')
    (s.wiki_dir / 'concepts/uncommitted.md').write_text('# Uncommitted')
    db.insert_source('fake-sha', 'text', 'fake.txt', 'fake-path', '[]')
    assert client.portal.call(recover, s, client.review_vault)
    assert db.get_task(tid)['status'] == 'failed'
    assert not db.list_sources() and not list(s.inbox_dir.iterdir())
    assert not (s.wiki_dir / 'concepts/uncommitted.md').exists()
    assert not list(s.private_raw_dir.iterdir())


def test_compensation_uses_real_adapter_and_cleans_ambiguous_create(client, monkeypatch, tmp_path):
    """真实适配器 + 测试 CLI；模拟保险柜已创建但返回响应丢失。"""
    from pathlib import Path
    from app.credentials.vaultwarden import VaultwardenAdapter
    from app.credentials.base import CredentialError
    from app.ingest.transaction import Transaction
    s = main.app.state.ctx.settings
    s.bw_binary = str(Path(__file__).with_name('fake_bw.py'))
    s.bw_email = 'fixture@example.test'; s.bw_password = 'fixture-master'
    state_path = tmp_path / 'bw-fixture.json'
    monkeypatch.setenv('BW_FAKE_STATE', str(state_path))
    adapter = VaultwardenAdapter(s)
    tid = accept(client, upload(client))
    tx = Transaction(s, adapter, tid)
    from app.credentials.base import SecretPayload
    run = adapter._run
    async def lost_response(*args, **kwargs):
        result = await run(*args, **kwargs)
        if args[:2] == ('create', 'item'):
            raise CredentialError('fixture lost response')
        return result
    monkeypatch.setattr(adapter, '_run', lost_response)
    async def scenario():
        with pytest.raises(CredentialError):
            await tx.create_secret(SecretPayload(name='fixture', value='fixture-secret', note='由资产 Agent 自动保存。'))
        assert len(json.loads(state_path.read_text())['items']) == 1
        await tx.rollback()
        assert json.loads(state_path.read_text())['items'] == []
    client.portal.call(scenario)


def test_cleanup_outage_blocks_later_tasks_until_recovered(client, monkeypatch):
    from app.credentials.base import CredentialError
    from app.ingest.transaction import Transaction
    s = main.app.state.ctx.settings
    tid = accept(client, upload(client))
    tx = Transaction(s, client.review_vault, tid)
    tx.state['vault_started'] = True; tx.save()
    db.update_task_status(tid, 'failed')
    second = accept(client, upload(client, [('later.txt', b'later content')]))
    original = client.review_vault.list_items
    async def down(): raise CredentialError('fixture unavailable')
    monkeypatch.setattr(client.review_vault, 'list_items', down)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(second)['status'] == 'planning_pending' and not client.review_model.calls
    assert tx.path.exists()
    monkeypatch.setattr(client.review_vault, 'list_items', original)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(second)['status'] == 'done' and not tx.path.exists()


def test_duplicate_queued_batch_reuses_task_and_keeps_payload(client):
    client.patch('/api/settings/security', json={'mode': 'default'})
    first, second = upload(client), upload(client)
    assert first['task_id'] == second['task_id']
    assert len(db.list_tasks()) == 1 and db.get_submission(first['submission_id'])['payload']
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(first['task_id'])['status'] == 'done'


def test_cross_file_manual_selection_rejected(client):
    view = upload(client)
    response = client.post(f"/api/pending/submissions/{view['submission_id']}/review", json={
        'session_id': client.review_session, 'manual': [{'source': 'document', 'start': 0, 'end': 40}]})
    assert response.status_code == 400


def test_private_raw_is_not_a_knowledge_directory(client, monkeypatch):
    from app.config import Settings
    monkeypatch.setenv('PRIVATE_RAW_DIR', str(main.app.state.ctx.settings.wiki_dir / 'sources'))
    with pytest.raises(ValueError, match='目录分开'):
        Settings().ensure_dirs()


def test_second_failed_round_preserves_old_archive_and_vault(client, monkeypatch):
    s = main.app.state.ctx.settings
    first = upload(client)
    first_tid = accept(client, first)
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(first_tid)['status'] == 'done'
    sources = [dict(row) for row in db.list_sources()]
    originals = {str(p): p.read_bytes() for p in s.private_raw_dir.rglob('*') if p.is_file()}
    removed = []
    async def delete(ref): removed.append(ref.item_id)
    monkeypatch.setattr(client.review_vault, 'delete_secret', delete)
    from tests.fakes import FixturePlanningProvider
    main.app.state.ctx.worker.get_provider = lambda: FixturePlanningProvider()
    def fail(*args, **kwargs): raise OSError('fixture index failure')
    monkeypatch.setattr(compiler, 'rebuild_index', fail)
    second_tid = accept(client, upload(client))
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(second_tid)['status'] == 'failed'
    assert not removed
    assert {str(p): p.read_bytes() for p in s.private_raw_dir.rglob('*') if p.is_file()} == originals
    assert [dict(row) for row in db.list_sources()] == sources
    assert len(db.sources_for_task(first_tid)) == 2 and not db.sources_for_task(second_tid)


def test_completed_task_is_not_rolled_back_if_journal_cleanup_fails(client, monkeypatch):
    from app.ingest.transaction import Transaction, recover
    original = Transaction.commit
    def fail_cleanup(self): raise OSError('fixture cleanup failure')
    monkeypatch.setattr(Transaction, 'commit', fail_cleanup)
    tid = accept(client, upload(client))
    client.portal.call(main.app.state.ctx.worker.tick)
    assert db.get_task(tid)['status'] == 'done'
    assert len(db.list_sources()) == 2
    s = main.app.state.ctx.settings
    assert list((s.data_dir / 'transactions').glob('*.json'))
    monkeypatch.setattr(Transaction, 'commit', original)
    assert client.portal.call(recover, s, client.review_vault)
    assert db.get_task(tid)['status'] == 'done' and len(db.list_sources()) == 2
