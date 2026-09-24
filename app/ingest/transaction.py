"""单进程维护事务：持久化补偿日志，只撤销本轮新凭证/原件并恢复知识状态。

SQLite、文件系统与保险柜没有分布式原子提交；保存前写日志，失败/重启补偿。
补偿未完成时阻止后续维护，保留日志，不宣称已经回滚。
"""
import base64
from contextvars import ContextVar
import json
import os
from pathlib import Path
import uuid

from .. import crypto, db
from ..credentials.base import SecretRef

active: ContextVar = ContextVar('maintenance_transaction', default=None)


def _atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('wb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


class Transaction:
    def __init__(self, settings, creds, task_id, state=None):
        self.settings, self.creds, self.task_id = settings, creds, task_id
        self.path = settings.data_dir / 'transactions' / f'{task_id}.json'
        self.state = state or dict(token=uuid.uuid4().hex, task_id=task_id,
                                  database=db.maintenance_snapshot(), files={}, vault=[], vault_started=False)
        if state is None:
            for path in settings.wiki_dir.rglob('*.md'):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(settings.wiki_dir.resolve()):
                    self.state['files'][str(path)] = base64.b64encode(path.read_bytes()).decode()
            index = settings.data_dir / 'wiki-index.json'
            self.state['files'][str(index)] = base64.b64encode(index.read_bytes()).decode() if index.exists() else None
            self.save()

    def save(self):
        _atomic(self.path, crypto.seal(self.settings.local_key(), json.dumps(self.state).encode()).encode())

    def track_new(self, path):
        if path.exists():
            raise ValueError('本轮文件目标已存在，已停止保存')
        self.state['files'][str(path)] = None
        self.save()

    def write_raw(self, path, text):
        self.track_new(path)
        _atomic(path, text.encode())

    def archive(self, name, content, position, original_sha=""):
        from .finalize import _safe_filename
        existing = db.archived_original(original_sha) if original_sha else None
        if existing and Path(existing['private_path']).is_file():
            return existing['private_path']
        # 不读取 Private Raw；唯一目录下以原文件格式写入，只公开位置元数据。
        suffix = Path(name).suffix
        safe_name = _safe_filename(Path(name).stem) + (_safe_filename(suffix) if suffix else '')
        path = self.settings.private_raw_dir / self.state['token'] / f'{position + 1}-{safe_name}'
        self.track_new(path)
        _atomic(path, content)
        return str(path)

    async def create_secret(self, payload):
        self.state['vault_started'] = True
        self.save()  # 超时或进程退出，仍可按事务标记找出已经在保险柜创建的条目。
        payload.note += f"; 维护事务: {self.state['token']}"
        ref = await self.creds.create_secret(payload)
        self.state['vault'].append(ref.item_id)
        self.save()
        return ref

    async def rollback(self):
        # 本地恢复先于远端清理；远端故障时仍保留日志，后续维护暂停。
        for path in self.settings.wiki_dir.rglob('*.md'):
            if str(path) not in self.state['files'] and not path.is_symlink():
                path.unlink()
        for name, previous in self.state['files'].items():
            path = Path(name)
            path.with_suffix(path.suffix + '.tmp').unlink(missing_ok=True)
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                _atomic(path, base64.b64decode(previous))
        archive_dir = self.settings.private_raw_dir / self.state['token']
        if archive_dir.exists():
            archive_dir.rmdir()
        db.restore_maintenance(self.state['database'], self.task_id)
        if self.state['vault_started']:
            items = await self.creds.list_items()
            owned = {m.item_id for m in items if getattr(m, 'transaction_id', '') == self.state['token']}
            present = {m.item_id for m in items}
            owned.update(set(self.state['vault']) & present)
            for item_id in owned:
                await self.creds.delete_secret(SecretRef(item_id=item_id))
        self.path.unlink(missing_ok=True)

    def commit(self):
        self.path.unlink(missing_ok=True)


async def recover(settings, creds):
    """返回 False 表示清理未完成；不让下一轮写入覆盖待恢复的知识状态。"""
    for path in sorted((settings.data_dir / 'transactions').glob('*.json')):
        try:
            state = json.loads(crypto.open_sealed(settings.local_key(), path.read_text()))
            tx = Transaction(settings, creds, state['task_id'], state)
            task = db.get_task(tx.task_id)
            if task and task['status'] == 'done':
                tx.commit()
                continue
            await tx.rollback()
            if task and task['report_id']:
                report = db.get_report(task['report_id'])
                if report and report['submission_id']:
                    db.resolve_submission(report['submission_id'], 'failed')
            db.update_task_status(tx.task_id, 'failed', error='维护已中断，本轮保存已回滚，请重新提交。')
        except Exception:
            db.log_security('rollback_failed', '维护补偿未完成，暂停后续维护。')
            return False
    return True
