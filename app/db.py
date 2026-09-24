"""SQLite 数据层：来源、任务、待处理凭证、对话记录、安全事件、模型配置、Wiki 页面。
单连接 + 全局锁：所有读写串行化（单用户 MVP 足够，避免跨线程并发损坏）。"""
import sqlite3
import threading
from pathlib import Path

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

# Session 固定模式：创建时一次选定，生命周期内不可切换。
SESSION_ASK = "ask"
SESSION_MAINTAIN = "maintain"
SESSION_MODES = (SESSION_ASK, SESSION_MAINTAIN)

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
  instruction TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  session_id TEXT,
  report_id INTEGER,
  status TEXT DEFAULT 'pending',
  error TEXT,
  result TEXT DEFAULT '{}',
  input_snapshot TEXT DEFAULT '{}',
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
  sha256 TEXT,
  kind TEXT,
  original_name TEXT,
  payload TEXT,
  status TEXT DEFAULT 'waiting',
  findings_summary TEXT DEFAULT '{}',
  session_id TEXT,
  report_id INTEGER,
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
  mode TEXT DEFAULT 'ask',
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
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  submission_id INTEGER,
  status TEXT DEFAULT 'pending',
  mode TEXT DEFAULT 'confirm',
  kind TEXT,
  original_name TEXT,
  sha256 TEXT,
  summary TEXT DEFAULT '{}',
  entries TEXT DEFAULT '[]',
  preview TEXT DEFAULT '',
  instruction TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  confirmed_at TEXT,
  maintenance_plan TEXT DEFAULT '{}',
  review_snapshot TEXT DEFAULT '{}'
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
    if "instruction" not in cols:
        _c().execute("ALTER TABLE sources ADD COLUMN instruction TEXT DEFAULT ''")
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
    # 1.0 重构：Session 固定模式、任务/待确认提交与报告关联、安全报告快照。
    scols = {r["name"] for r in _c().execute("PRAGMA table_info(chat_sessions)")}
    if "mode" not in scols:
        # 旧会话无模式：默认 ask（只读，fail-closed；写操作必须显式建维护会话）。
        _c().execute("ALTER TABLE chat_sessions ADD COLUMN mode TEXT DEFAULT 'ask'")
    tcols = {r["name"] for r in _c().execute("PRAGMA table_info(tasks)")}
    if "session_id" not in tcols:
        _c().execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
    if "report_id" not in tcols:
        _c().execute("ALTER TABLE tasks ADD COLUMN report_id INTEGER")
    if "result" not in tcols:
        _c().execute("ALTER TABLE tasks ADD COLUMN result TEXT DEFAULT '{}'")
    if "input_snapshot" not in tcols:
        _c().execute("ALTER TABLE tasks ADD COLUMN input_snapshot TEXT DEFAULT '{}'")
    pcols = {r["name"] for r in _c().execute("PRAGMA table_info(pending_submissions)")}
    if "session_id" not in pcols:
        _c().execute("ALTER TABLE pending_submissions ADD COLUMN session_id TEXT")
    if "report_id" not in pcols:
        _c().execute("ALTER TABLE pending_submissions ADD COLUMN report_id INTEGER")
    rcols = {r["name"] for r in _c().execute("PRAGMA table_info(reports)")}
    if "instruction" not in rcols:
        _c().execute("ALTER TABLE reports ADD COLUMN instruction TEXT DEFAULT ''")
    if "maintenance_plan" not in rcols:
        _c().execute("ALTER TABLE reports ADD COLUMN maintenance_plan TEXT DEFAULT '{}'")
    if "review_snapshot" not in rcols:
        _c().execute("ALTER TABLE reports ADD COLUMN review_snapshot TEXT DEFAULT '{}'")
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
    # 待确认提交按「会话 + 内容」唯一（waiting 态）：同一会话重复提交安全幂等，
    # 不同会话各自拥有自己的提交与报告（Source 内容去重独立于会话）。
    _c().execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_submission_session_sha "
        "ON pending_submissions(session_id, sha256) WHERE status='waiting'"
    )
    _c().commit()


def kv_get(key: str, default=None):
    row = _r1("SELECT value FROM kv WHERE key=?", (key,))
    return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    _w("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def insert_source(sha256: str, kind: str, original_name: str, path: str, secret_refs: str,
                  confirmed: int = 1, allowed_spans: str = "[]", instruction: str = "") -> int:
    return _w(
        "INSERT INTO sources(sha256,kind,original_name,path,secret_refs,confirmed,allowed_spans,instruction) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (sha256, kind, original_name, path, secret_refs, confirmed, allowed_spans, instruction),
    ).lastrowid


def get_source_by_sha256(sha256: str):
    return _r1("SELECT * FROM sources WHERE sha256=?", (sha256,))


def update_source_processed(source_id: int, path: str, secret_refs: str, allowed_spans: str,
                            instruction: str | None = None) -> None:
    """占位行完成落盘：写入路径/引用/放行区间并标记已通过确认闸门。"""
    if instruction is not None:
        _w(
            "UPDATE sources SET path=?, secret_refs=?, allowed_spans=?, confirmed=1, instruction=? WHERE id=?",
            (path, secret_refs, allowed_spans, instruction, source_id),
        )
        return
    _w(
        "UPDATE sources SET path=?, secret_refs=?, allowed_spans=?, confirmed=1 WHERE id=?",
        (path, secret_refs, allowed_spans, source_id),
    )


def delete_source_by_sha256(sha256: str) -> int:
    return _w("DELETE FROM sources WHERE sha256=?", (sha256,)).rowcount


def get_source(source_id: int):
    return _r1("SELECT * FROM sources WHERE id=?", (source_id,))


def source_refs(source_id: int) -> list[dict]:
    """只读返回来源的登记私密引用元数据（解析后的 ref 列表；不含任何秘密原文）。
    来源不存在或未确认时返回空列表。"""
    import json

    row = _r1("SELECT secret_refs, confirmed FROM sources WHERE id=?", (source_id,))
    if not row or not row["confirmed"]:
        return []
    try:
        return json.loads(row["secret_refs"] or "[]")
    except json.JSONDecodeError:
        return []


def all_source_refs() -> list[dict]:
    """只读汇总所有已确认来源的登记私密引用元数据（解析后的 ref 列表；不含秘密原文）。"""
    import json

    out: list[dict] = []
    for row in _r("SELECT secret_refs FROM sources WHERE confirmed=1"):
        try:
            out.extend(json.loads(row["secret_refs"] or "[]"))
        except json.JSONDecodeError:
            continue
    # 重复来源的每轮安全快照只在裁决/复扫后创建；不能信任待确认报告。
    for row in _r("SELECT t.input_snapshot FROM tasks t JOIN sources s ON s.id=t.source_id "
                  "WHERE s.confirmed=1 AND t.input_snapshot != '{}'"):
        out.extend(json.loads(row["input_snapshot"] or "{}").get("refs", []))
    return out


def list_sources(limit: int = 100):
    return _r("SELECT * FROM sources ORDER BY id DESC LIMIT ?", (limit,))


def insert_task(source_id: int, session_id: str | None = None, report_id: int | None = None,
                input_snapshot: str = "{}") -> int:
    return _w(
        "INSERT INTO tasks(source_id, session_id, report_id, input_snapshot) VALUES(?,?,?,?)",
        (source_id, session_id, report_id, input_snapshot),
    ).lastrowid


def update_task_status(task_id: int, status: str, error: str | None = None) -> None:
    _w("UPDATE tasks SET status=?, error=?, updated_at=datetime('now','localtime') WHERE id=?", (status, error, task_id))


def set_task_result(task_id: int, result: str) -> None:
    _w("UPDATE tasks SET result=? WHERE id=?", (result, task_id))


def set_task_report(task_id: int, report_id: int) -> None:
    _w("UPDATE tasks SET report_id=? WHERE id=?", (report_id, task_id))


def update_task_retries(task_id: int) -> None:
    _w("UPDATE tasks SET retries=retries+1 WHERE id=?", (task_id,))


def get_task(task_id: int):
    return _r1("SELECT * FROM tasks WHERE id=?", (task_id,))


def list_tasks(statuses=None, limit: int = 100):
    q = "SELECT t.*, COALESCE(s.original_name,r.original_name) AS original_name, COALESCE(s.kind,r.kind) AS kind FROM tasks t LEFT JOIN sources s ON s.id=t.source_id LEFT JOIN reports r ON r.id=t.report_id "
    args = []
    if statuses:
        q += "WHERE t.status IN (%s) " % ",".join("?" * len(statuses))
        args.extend(statuses)
    q += "ORDER BY t.id DESC LIMIT ?"
    args.append(limit)
    return _r(q, args)


def maintenance_history(session_id: str, before_task_id: int):
    return _r(
        "SELECT t.id,t.status,t.result,t.error,r.preview,r.instruction FROM tasks t "
        "JOIN reports r ON r.id=t.report_id "
        "WHERE t.session_id=? AND r.session_id=? AND t.id<? AND t.status IN ('done','failed') "
        "AND r.status IN ('confirmed','auto') ORDER BY t.id DESC LIMIT 3",
        (session_id, session_id, before_task_id),
    )


def tasks_by_source(source_id: int):
    return _r("SELECT * FROM tasks WHERE source_id=?", (source_id,))


def latest_task_for_source(source_id: int):
    return _r1("SELECT * FROM tasks WHERE source_id=? ORDER BY id DESC LIMIT 1", (source_id,))


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

def insert_submission(sha256: str, kind: str, original_name: str, payload: str, findings_summary: str,
                      session_id: str | None = None, report_id: int | None = None) -> int:
    return _w(
        "INSERT INTO pending_submissions(sha256,kind,original_name,payload,findings_summary,session_id,report_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (sha256, kind, original_name, payload, findings_summary, session_id, report_id),
    ).lastrowid


def delete_stale_submissions(sha256: str, session_id: str | None = None) -> int:
    """清除同一会话内同一内容的非等待态提交（取消/过期），
    避免 (session_id, sha256) 唯一冲突且不留旧密文；不影响其他会话的提交。"""
    if session_id is not None:
        return _w(
            "DELETE FROM pending_submissions WHERE session_id=? AND sha256=? AND status!='waiting'",
            (session_id, sha256),
        ).rowcount
    return _w("DELETE FROM pending_submissions WHERE sha256=? AND status!='waiting'", (sha256,)).rowcount


def get_submission(submission_id: int):
    return _r1("SELECT * FROM pending_submissions WHERE id=?", (submission_id,))


def submission_by_sha256(sha256: str, session_id: str | None = None):
    """按会话查重：同一会话重复提交返回既有等待提交；跨会话不合并。"""
    if session_id is not None:
        return _r1(
            "SELECT * FROM pending_submissions WHERE session_id=? AND sha256=? AND status='waiting'",
            (session_id, sha256),
        )
    return _r1("SELECT * FROM pending_submissions WHERE sha256=? AND status='waiting'", (sha256,))


def list_submissions(status: str | None = None):
    if status:
        return _r("SELECT * FROM pending_submissions WHERE status=? ORDER BY id DESC", (status,))
    return _r("SELECT * FROM pending_submissions ORDER BY id DESC")


def submission_count_waiting() -> int:
    row = _r1("SELECT COUNT(*) AS n FROM pending_submissions WHERE status='waiting'")
    return row["n"] if row else 0


def queue_submission_plan(submission_id: int, payload: str, state: str, review_snapshot: str = "{}") -> int | None:
    """一次确认原子创建任务并锁定密文草稿；后台成功/失败后销毁密文。"""
    with _lock:
        with _c():
            row = _c().execute("SELECT report_id,session_id FROM pending_submissions WHERE id=? AND status='waiting'", (submission_id,)).fetchone()
            if not row:
                return None
            report = _c().execute("UPDATE reports SET maintenance_plan=?,review_snapshot=? WHERE id=? AND status='pending'", (state, review_snapshot, row['report_id']))
            if not report.rowcount:
                return None
            task = _c().execute("INSERT INTO tasks(session_id,report_id,status) VALUES(?,?,'planning_pending')", (row['session_id'], row['report_id']))
            _c().execute("UPDATE pending_submissions SET payload=?, status='processing' WHERE id=?", (payload, submission_id))
        return task.lastrowid


def task_for_report(report_id: int):
    return _r1("SELECT * FROM tasks WHERE report_id=? ORDER BY id DESC LIMIT 1", (report_id,))


def bind_task_source(task_id: int, source_id: int, snapshot: str) -> None:
    _w("UPDATE tasks SET source_id=?,input_snapshot=? WHERE id=?", (source_id, snapshot, task_id))


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


def create_session(session_id: str, mode: str, title: str | None = None) -> None:
    """显式创建固定模式会话。已存在且模式不同 → 拒绝（生命周期内不可切换）。
    已存在且模式相同 → 幂等，仅补写标题。"""
    if mode not in SESSION_MODES:
        raise ValueError(f"会话模式必须是 {SESSION_MODES} 之一")
    with _lock:
        row = _c().execute("SELECT mode FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row and row["mode"] != mode:
            raise ValueError(f"会话 {session_id} 已固定为 {row['mode']} 模式，不能切换为 {mode}")
        _c().execute(
            "INSERT INTO chat_sessions(session_id, mode, title) VALUES(?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET title=COALESCE(excluded.title, chat_sessions.title)",
            (session_id, mode, title),
        )
        _c().commit()


def get_session(session_id: str):
    return _r1("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,))


def session_mode(session_id: str) -> str | None:
    row = get_session(session_id)
    return row["mode"] if row else None


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


# ---- 安全报告（固定格式快照，无明文持久化） ----

def insert_report(session_id: str | None, submission_id: int | None, status: str, mode: str,
                  kind: str, original_name: str, sha256: str, summary: str, entries: str,
                  preview: str, instruction: str = "", review_snapshot: str = "{}") -> int:
    confirmed_at = "datetime('now','localtime')" if status in ("confirmed", "auto") else "NULL"
    return _w(
        "INSERT INTO reports(session_id,submission_id,status,mode,kind,original_name,sha256,"
        "summary,entries,preview,instruction,review_snapshot,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?," + confirmed_at + ")",
        (session_id, submission_id, status, mode, kind, original_name, sha256, summary, entries, preview, instruction, review_snapshot),
    ).lastrowid


def get_report(report_id: int):
    return _r1("SELECT * FROM reports WHERE id=?", (report_id,))


def update_report(report_id: int, *, status: str | None = None, submission_id: int | None = None,
                  summary: str | None = None, entries: str | None = None,
                  preview: str | None = None, instruction: str | None = None,
                  maintenance_plan: str | None = None, review_snapshot: str | None = None) -> None:
    """报告字段更新；仅 pending 态可改。终态（confirmed/auto/rejected）原子锁定：
    用条件更新 WHERE status='pending' 保证失败不改原值，锁定后任何字段/状态修改均被拒绝。"""
    sets: list[str] = []
    args: list = []
    if status is not None:
        sets.append("status=?")
        args.append(status)
        if status in ("confirmed", "auto"):
            sets.append("confirmed_at=datetime('now','localtime')")
    if submission_id is not None:
        sets.append("submission_id=?")
        args.append(submission_id)
    if summary is not None:
        sets.append("summary=?")
        args.append(summary)
    if entries is not None:
        sets.append("entries=?")
        args.append(entries)
    if preview is not None:
        sets.append("preview=?")
        args.append(preview)
    if instruction is not None:
        sets.append("instruction=?")
        args.append(instruction)
    if maintenance_plan is not None:
        sets.append("maintenance_plan=?")
        args.append(maintenance_plan)
    if review_snapshot is not None:
        sets.append("review_snapshot=?")
        args.append(review_snapshot)
    if not sets:
        return
    args.append(report_id)
    with _lock:
        cur = _c().execute(
            f"UPDATE reports SET {', '.join(sets)} WHERE id=? AND status='pending'", args
        )
        if cur.rowcount == 0:
            row = _c().execute("SELECT status FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise ValueError("报告不存在")
            raise ValueError(f"报告已锁定（{row['status']}），不可修改")
        _c().commit()


def list_reports_by_session(session_id: str):
    return _r("SELECT * FROM reports WHERE session_id=? ORDER BY id DESC", (session_id,))


def list_reports():
    return _r("SELECT * FROM reports ORDER BY id DESC")


def report_view(report_id: int) -> dict | None:
    """报告只读视图：解析结构化字段（summary/entries），供前端展示。"""
    import json

    row = get_report(report_id)
    if not row:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "submission_id": row["submission_id"],
        "status": row["status"],
        "mode": row["mode"],
        "kind": row["kind"],
        "original_name": row["original_name"],
        "sha256": (row["sha256"] or "")[:16],
        "summary": _json_loads_default(row["summary"]),
        "entries": _json_loads_default(row["entries"]),
        "review_snapshot": _json_loads_default(row["review_snapshot"]),
        "preview": row["preview"] or "",
        "instruction": row["instruction"] or "",
        "maintenance_plan": _json_loads_default(row["maintenance_plan"]).get("plan"),
        "plan_status": _json_loads_default(row["maintenance_plan"]).get("status"),
        "plan_error": _json_loads_default(row["maintenance_plan"]).get("error"),
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"],
    }


def _json_loads_default(s: str | None):
    import json

    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        return {}


def find_ref_metadata(ref_id: str) -> dict | None:
    """按私密引用 ID 定位安全元数据（来源/会话/保险柜条目与字段位置）。
    只对「已确认/自动且已写入保险柜」的条目提供位置；拒绝/待确认/未保存返回 None。
    同 ref_id 多份报告时返回最近已落库条目。绝不返回敏感原值、值哈希或笔记正文。"""
    import json

    for row in _r(
        "SELECT id, session_id, original_name, kind, created_at, status, entries "
        "FROM reports ORDER BY id DESC"
    ):
        if row["status"] not in ("confirmed", "auto"):
            continue  # pending/rejected 尚未真正落库，不作为可用位置
        for e in json.loads(row["entries"] or "[]"):
            if e.get("ref_id") == ref_id:
                vault = e.get("vault") or {}
                if not vault.get("item_id"):
                    continue  # 挂起未写入保险柜，不作为可用位置
                return {
                    "ref_id": ref_id,
                    "name": e.get("name"),
                    "source": e.get("source") or row["original_name"],
                    "kind": row["kind"],
                    "vault_kind": vault.get("kind"),
                    "vault_name": vault.get("name"),
                    "field_name": vault.get("field_name"),
                    "item_id": vault.get("item_id"),
                    "report_id": row["id"],
                    "session_id": row["session_id"],
                    "created_at": row["created_at"],
                }
    return None
