"""SQLite 数据层：来源、任务、待处理凭证、对话记录、安全事件、模型配置、Wiki 页面。
单连接 + 全局锁：所有读写串行化（单用户 MVP 足够，避免跨线程并发损坏）。"""
import sqlite3
import threading
from pathlib import Path

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE,
  kind TEXT,
  original_name TEXT,
  path TEXT,
  secret_refs TEXT DEFAULT '[]',
  confirmed INTEGER DEFAULT 1,
  allowed_spans TEXT DEFAULT '[]',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  status TEXT DEFAULT 'pending',
  error TEXT,
  retries INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS pending_secrets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  name TEXT,
  sha256 TEXT,
  payload TEXT,
  status TEXT DEFAULT 'pending',
  retries INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS pending_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE,
  kind TEXT,
  original_name TEXT,
  payload TEXT,
  status TEXT DEFAULT 'waiting',
  findings_summary TEXT DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT,
  answer TEXT,
  citations TEXT DEFAULT '[]',
  session_id TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id TEXT PRIMARY KEY,
  title TEXT,
  pinned INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  detail TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS model_configs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  provider_type TEXT,
  base_url TEXT,
  api_key_enc TEXT,
  model TEXT,
  is_active INTEGER DEFAULT 0,
  role TEXT DEFAULT 'knowledge',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS retrieval_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  reranker_enabled INTEGER NOT NULL DEFAULT 1,
  reranker_model TEXT NOT NULL DEFAULT '',
  cloud_base_url TEXT NOT NULL DEFAULT '',
  cloud_api_key_enc TEXT NOT NULL DEFAULT '',
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS pages_data (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  title TEXT,
  content TEXT,
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

def _c() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db 未初始化")
    return _conn


def _q(sql: str, params=()):
    """锁内执行并返回游标结果（需要 commit 的写操作调用 _w）。"""
    return _c().execute(sql, params)


def _w(sql: str, params=()):
    with _lock:
        cur = _c().execute(sql, params)
        _c().commit()
        return cur


def _r(sql: str, params=()):
    with _lock:
        return _c().execute(sql, params).fetchall()


def _r1(sql: str, params=()):
    with _lock:
        return _c().execute(sql, params).fetchone()


def init(path: Path) -> None:
    global _conn
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)
        _migrate()
        _conn.commit()


def _migrate() -> None:
    """轻量迁移：老库补列。sources.confirmed=1 表示已通过确认闸门（历史数据视为已确认）。
    model_configs.role 缺失时补 knowledge（老库唯一模型即知识库模型），并按角色归一化
    多激活：knowledge/security 各自最多保留一个激活配置（fail-closed，不放大模型调用面）。"""
    cols = {r["name"] for r in _c().execute("PRAGMA table_info(sources)")}
    if "confirmed" not in cols:
        _c().execute("ALTER TABLE sources ADD COLUMN confirmed INTEGER DEFAULT 1")
    if "allowed_spans" not in cols:
        _c().execute("ALTER TABLE sources ADD COLUMN allowed_spans TEXT DEFAULT '[]'")
    # FTS5 查询路径已退役：清理旧库遗留的虚拟表、触发器与开关位（派生索引，可随时从 Markdown 重建）。
    _c().executescript(
        "DROP TRIGGER IF EXISTS pages_ai;"
        "DROP TRIGGER IF EXISTS pages_ad;"
        "DROP TRIGGER IF EXISTS pages_au;"
        "DROP TABLE IF EXISTS pages_fts;"
    )
    _c().execute("DELETE FROM kv WHERE key='fts_enabled'")
    mcols = {r["name"] for r in _c().execute("PRAGMA table_info(model_configs)")}
    if "role" not in mcols:
        _c().execute("ALTER TABLE model_configs ADD COLUMN role TEXT DEFAULT 'knowledge'")
    ccols = {r["name"] for r in _c().execute("PRAGMA table_info(chat_log)")}
    if "session_id" not in ccols:
        _c().execute("ALTER TABLE chat_log ADD COLUMN session_id TEXT")
    for role in ("knowledge", "security"):
        rows = _c().execute(
            "SELECT id FROM model_configs WHERE role=? AND is_active=1 ORDER BY id", (role,)
        ).fetchall()
        for r in rows[1:]:
            _c().execute("UPDATE model_configs SET is_active=0 WHERE id=?", (r["id"],))
    # 每角色至多一个激活的数据库级约束（先归一化再建索引，避免老库多激活数据建索引失败）
    _c().execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_configs_active_role "
        "ON model_configs(role) WHERE is_active=1"
    )
    _c().commit()


def kv_get(key: str, default=None):
    row = _r1("SELECT value FROM kv WHERE key=?", (key,))
    return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    _w("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def insert_source(sha256: str, kind: str, original_name: str, path: str, secret_refs: str,
                  confirmed: int = 1, allowed_spans: str = "[]") -> int:
    return _w(
        "INSERT INTO sources(sha256,kind,original_name,path,secret_refs,confirmed,allowed_spans) "
        "VALUES(?,?,?,?,?,?,?)",
        (sha256, kind, original_name, path, secret_refs, confirmed, allowed_spans),
    ).lastrowid


def get_source_by_sha256(sha256: str):
    return _r1("SELECT * FROM sources WHERE sha256=?", (sha256,))


def update_source_processed(source_id: int, path: str, secret_refs: str, allowed_spans: str) -> None:
    """占位行完成落盘：写入路径/引用/放行区间并标记已通过确认闸门。"""
    _w(
        "UPDATE sources SET path=?, secret_refs=?, allowed_spans=?, confirmed=1 WHERE id=?",
        (path, secret_refs, allowed_spans, source_id),
    )


def delete_source_by_sha256(sha256: str) -> int:
    return _w("DELETE FROM sources WHERE sha256=?", (sha256,)).rowcount


def get_source(source_id: int):
    return _r1("SELECT * FROM sources WHERE id=?", (source_id,))


def list_sources(limit: int = 100):
    return _r("SELECT * FROM sources ORDER BY id DESC LIMIT ?", (limit,))


def insert_task(source_id: int) -> int:
    return _w("INSERT INTO tasks(source_id) VALUES(?)", (source_id,)).lastrowid


def update_task_status(task_id: int, status: str, error: str | None = None) -> None:
    _w("UPDATE tasks SET status=?, error=?, updated_at=datetime('now','localtime') WHERE id=?", (status, error, task_id))


def update_task_retries(task_id: int) -> None:
    _w("UPDATE tasks SET retries=retries+1 WHERE id=?", (task_id,))


def get_task(task_id: int):
    return _r1("SELECT * FROM tasks WHERE id=?", (task_id,))


def list_tasks(statuses=None, limit: int = 100):
    q = "SELECT t.*, s.original_name, s.kind FROM tasks t LEFT JOIN sources s ON s.id=t.source_id "
    args = []
    if statuses:
        q += "WHERE t.status IN (%s) " % ",".join("?" * len(statuses))
        args.extend(statuses)
    q += "ORDER BY t.id DESC LIMIT ?"
    args.append(limit)
    return _r(q, args)


def tasks_by_source(source_id: int):
    return _r("SELECT * FROM tasks WHERE source_id=?", (source_id,))


def insert_pending(source_id, name: str, sha256: str, payload: str) -> int:
    return _w("INSERT INTO pending_secrets(source_id,name,sha256,payload) VALUES(?,?,?,?)",
              (source_id, name, sha256, payload)).lastrowid


def update_pending_source(pending_id: int, source_id: int) -> None:
    _w("UPDATE pending_secrets SET source_id=? WHERE id=?", (source_id, pending_id))


def update_pending(pending_id: int, status: str) -> None:
    _w("UPDATE pending_secrets SET status=?, resolved_at=datetime('now','localtime') WHERE id=?", (status, pending_id))


def update_pending_retry(pending_id: int) -> None:
    _w("UPDATE pending_secrets SET retries=retries+1 WHERE id=?", (pending_id,))


def delete_pending(pending_id: int) -> None:
    _w("DELETE FROM pending_secrets WHERE id=?", (pending_id,))


def delete_pending_by_source(source_id: int) -> int:
    return _w("DELETE FROM pending_secrets WHERE source_id=?", (source_id,)).rowcount


def list_pending(status: str | None = None):
    if status:
        return _r("SELECT * FROM pending_secrets WHERE status=?", (status,))
    return _r("SELECT * FROM pending_secrets")


def pending_by_source_open(source_id: int) -> int:
    row = _r1("SELECT COUNT(*) AS n FROM pending_secrets WHERE source_id=? AND status='pending'", (source_id,))
    return row["n"] if row else 0


# ---- 待确认提交（确认闸门：原文以 AES-256-GCM 密文暂存，确认前不落盘、不进模型） ----

def insert_submission(sha256: str, kind: str, original_name: str, payload: str, findings_summary: str) -> int:
    return _w(
        "INSERT INTO pending_submissions(sha256,kind,original_name,payload,findings_summary) VALUES(?,?,?,?,?)",
        (sha256, kind, original_name, payload, findings_summary),
    ).lastrowid


def delete_stale_submissions(sha256: str) -> int:
    """清除同一内容的非等待态提交（取消/过期），避免 sha256 UNIQUE 冲突且不留旧密文。"""
    return _w("DELETE FROM pending_submissions WHERE sha256=? AND status!='waiting'", (sha256,)).rowcount


def get_submission(submission_id: int):
    return _r1("SELECT * FROM pending_submissions WHERE id=?", (submission_id,))


def submission_by_sha256(sha256: str):
    return _r1("SELECT * FROM pending_submissions WHERE sha256=? AND status='waiting'", (sha256,))


def list_submissions(status: str | None = None):
    if status:
        return _r("SELECT * FROM pending_submissions WHERE status=? ORDER BY id DESC", (status,))
    return _r("SELECT * FROM pending_submissions ORDER BY id DESC")


def submission_count_waiting() -> int:
    row = _r1("SELECT COUNT(*) AS n FROM pending_submissions WHERE status='waiting'")
    return row["n"] if row else 0


def resolve_submission(submission_id: int, status: str) -> None:
    """确认/取消/过期：清除密文（销毁临时明文），仅保留审计用元数据。"""
    _w(
        "UPDATE pending_submissions SET status=?, payload='', resolved_at=datetime('now','localtime') WHERE id=?",
        (status, submission_id),
    )


def delete_submission(submission_id: int) -> None:
    _w("DELETE FROM pending_submissions WHERE id=?", (submission_id,))


def insert_chat(question: str, answer: str, citations, session_id: str | None = None) -> None:
    import json

    _w("INSERT INTO chat_log(question,answer,citations,session_id) VALUES(?,?,?,?)",
       (question, answer, json.dumps(citations, ensure_ascii=False), session_id))


def list_chat(limit: int = 50):
    return _r("SELECT * FROM chat_log ORDER BY id DESC LIMIT ?", (limit,))


def list_chat_history(session_id: str, limit: int) -> list:
    """会话最近 limit 轮问答（按时间升序），供每次请求水合对话记忆。
    chat_log 是对话历史唯一持久化事实源；本函数只读、不写入任何存储。"""
    return _r(
        "SELECT id, question, answer FROM ("
        "SELECT id, question, answer FROM chat_log WHERE session_id=? "
        "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
        (session_id, limit),
    )


def ensure_session(session_id: str) -> None:
    _w("INSERT OR IGNORE INTO chat_sessions(session_id) VALUES(?)", (session_id,))


def adopt_session(session_id: str, entry_ids) -> None:
    ensure_session(session_id)
    for i in entry_ids:
        _w("UPDATE chat_log SET session_id=? WHERE id=?", (session_id, i))


def set_session_title(session_id: str, title: str) -> None:
    ensure_session(session_id)
    _w("UPDATE chat_sessions SET title=? WHERE session_id=?", (title, session_id))


def set_session_pinned(session_id: str, pinned: bool) -> None:
    ensure_session(session_id)
    _w("UPDATE chat_sessions SET pinned=? WHERE session_id=?", (1 if pinned else 0, session_id))


def delete_session(session_id: str) -> None:
    _w("DELETE FROM chat_log WHERE session_id=?", (session_id,))
    _w("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))


def list_sessions():
    return _r("SELECT * FROM chat_sessions")


def log_security(kind: str, detail: str) -> None:
    _w("INSERT INTO security_events(kind,detail) VALUES(?,?)", (kind, detail[:2000]))


def list_security(limit: int = 50):
    return _r("SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,))


def clear_security() -> None:
    _w("DELETE FROM security_events")


def upsert_model_config(cfg_id, name, provider_type, base_url, api_key_enc, model, is_active,
                        role: str = "knowledge") -> int:
    """保存配置；is_active 时在单事务内先停用同角色其他配置再激活本配置
    （原子切换，配合 idx_model_configs_active_role 部分唯一索引保证每角色至多一个激活）。"""
    with _lock:
        if is_active:
            _c().execute("UPDATE model_configs SET is_active=0 WHERE role=? AND id!=?",
                         (role, cfg_id or -1))
        if cfg_id:
            _c().execute("""UPDATE model_configs SET name=?, provider_type=?, base_url=?, api_key_enc=?, model=?, is_active=?, role=?
                            WHERE id=?""",
                         (name, provider_type, base_url, api_key_enc, model, 1 if is_active else 0, role, cfg_id))
        else:
            cur = _c().execute(
                """INSERT INTO model_configs(name,provider_type,base_url,api_key_enc,model,is_active,role)
                   VALUES(?,?,?,?,?,?,?)""",
                (name, provider_type, base_url, api_key_enc, model, 1 if is_active else 0, role),
            )
            cfg_id = cur.lastrowid
        _c().commit()
        return cfg_id


def get_model_config(cfg_id: int):
    return _r1("SELECT * FROM model_configs WHERE id=?", (cfg_id,))


def list_model_configs():
    return _r("SELECT * FROM model_configs ORDER BY id")


def get_active_model_config(role: str = "knowledge"):
    """当前角色唯一激活的模型配置（迁移归一化保证每角色至多一条激活）。"""
    return _r1("SELECT * FROM model_configs WHERE role=? AND is_active=1 ORDER BY id", (role,))


def delete_model_config(cfg_id: int) -> None:
    _w("DELETE FROM model_configs WHERE id=?", (cfg_id,))


def activate_model_config(cfg_id: int) -> None:
    """激活指定配置并仅停用同角色其他配置：knowledge/security 各自独立、各至多一个激活。"""
    with _lock:
        row = _c().execute("SELECT role FROM model_configs WHERE id=?", (cfg_id,)).fetchone()
        if row is None:
            return
        role = row["role"]
        _c().execute("UPDATE model_configs SET is_active=0 WHERE role=?", (role,))
        _c().execute("UPDATE model_configs SET is_active=1 WHERE id=?", (cfg_id,))
        _c().commit()


def upsert_page(path: str, title: str, content: str) -> None:
    _w(
        """INSERT INTO pages_data(path,title,content,updated_at) VALUES(?,?,?,datetime('now','localtime'))
           ON CONFLICT(path) DO UPDATE SET title=excluded.title, content=excluded.content,
           updated_at=excluded.updated_at""",
        (path, title, content),
    )


def delete_page(path: str) -> None:
    _w("DELETE FROM pages_data WHERE path=?", (path,))


def list_pages():
    return _r("SELECT * FROM pages_data ORDER BY path")


def get_page(path: str):
    return _r1("SELECT * FROM pages_data WHERE path=?", (path,))


# ---- 检索配置（问答子系统）：页面写入优先于环境变量 ----

def get_retrieval_config():
    return _r1("SELECT * FROM retrieval_config WHERE id=1")


def save_retrieval_config(provider: str, model: str, reranker_enabled: int, reranker_model: str,
                          cloud_base_url: str, cloud_api_key_enc: str) -> None:
    _w(
        """INSERT INTO retrieval_config(id,provider,model,reranker_enabled,reranker_model,cloud_base_url,cloud_api_key_enc,updated_at)
           VALUES(1,?,?,?,?,?,?,datetime('now','localtime'))
           ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, model=excluded.model,
             reranker_enabled=excluded.reranker_enabled, reranker_model=excluded.reranker_model,
             cloud_base_url=excluded.cloud_base_url, cloud_api_key_enc=excluded.cloud_api_key_enc,
             updated_at=excluded.updated_at""",
        (provider, model, reranker_enabled, reranker_model, cloud_base_url, cloud_api_key_enc),
    )


def delete_retrieval_config() -> None:
    _w("DELETE FROM retrieval_config WHERE id=1")
