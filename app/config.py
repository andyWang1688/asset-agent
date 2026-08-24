"""运行时配置：全部通过环境变量注入，代码中不写死任何模型或凭证信息。"""
import base64
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def file_env(name: str, default: str | None = None) -> str | None:
    """优先读环境变量；若存在 <NAME>_FILE 则读取该文件内容（Docker Secret 方式）。"""
    value = os.environ.get(name)
    if value:
        return value
    path = os.environ.get(f"{name}_FILE")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return default


class Settings:
    def __init__(self) -> None:
        self.workspace_dir = Path(os.environ.get("WORKSPACE_DIR", str(BASE_DIR / "workspace")))
        self.data_dir = Path(os.environ.get("DATA_DIR", str(self.workspace_dir / ".asset-assistant")))
        self.raw_dir = self.workspace_dir / "raw"
        self.inbox_dir = self.raw_dir / "inbox"
        self.attachments_dir = self.raw_dir / "attachments"
        self.wiki_dir = self.workspace_dir / "wiki"
        self.schema_file = self.workspace_dir / "schema" / "AGENTS.md"
        self.schema_builtin = BASE_DIR / "schema" / "AGENTS.md"

        self.local_key_file = os.environ.get("LOCAL_KEY_FILE")
        self.vaultwarden_url = (file_env("VAULTWARDEN_URL", "http://127.0.0.1:8081") or "").rstrip("/")
        self.bw_email = file_env("BW_EMAIL")
        self.bw_password = file_env("BW_PASSWORD")
        self.bw_clientid = file_env("BW_CLIENTID")
        self.bw_clientsecret = file_env("BW_CLIENTSECRET")
        self.bw_binary = os.environ.get("BW_BINARY", "bw")
        self.bw_config_dir = os.environ.get("BITWARDENCLI_APPDATA_DIR", str(self.data_dir / "bw-cli"))

        self.http_timeout = float(os.environ.get("HTTP_TIMEOUT", "180"))
        self.max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "10"))
        self.queue_ttl_seconds = int(os.environ.get("QUEUE_TTL_SECONDS", str(7 * 24 * 3600)))
        self.queue_retry_seconds = int(os.environ.get("QUEUE_RETRY_SECONDS", "30"))
        self.policy_file = Path(os.environ.get("POLICY_FILE", str(self.data_dir / "config" / "policy.yaml")))
        # 问答检索引擎已收敛为单一混合引擎（BM25+向量+重排）；embedding 默认本地。
        # 混合引擎的重排器：local（默认精排）或 off（停用，退回纯召回）。
        self.reranker = os.environ.get("RERANKER", "local").strip().lower()
        # 对话记忆：每次提问从 chat_log 水合的最近轮数；<=0 关闭记忆。
        self.chat_memory_rounds = int(os.environ.get("CHAT_MEMORY_ROUNDS", "6"))
        self.embedding_provider = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()
        self.embedding_local_backend = os.environ.get("EMBEDDING_LOCAL_BACKEND", "hash").strip().lower()
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        self.embedding_base_url = (
            os.environ.get("EMBEDDING_BASE_URL")
            or os.environ.get("OLLAMA_BASE_URL")
            or ""
        ).rstrip("/")
        self.embedding_api_key = file_env("EMBEDDING_API_KEY", "") or ""
        self.embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "384"))
        self.embedding_timeout = float(os.environ.get("EMBEDDING_TIMEOUT", str(self.http_timeout)))
        # 待确认队列密钥：PENDING_QUEUE_KEY_FILE 指向密钥文件（hex/base64/32 字节原文），
        # 支持 PENDING_QUEUE_KEY_FILE_FILE 间接层（Docker Secret 挂载）。未配置时回退 local_key()。
        self.pending_queue_key_file = (
            os.environ.get("PENDING_QUEUE_KEY_FILE") or os.environ.get("PENDING_QUEUE_KEY_FILE_FILE")
        )
        self.pending_submission_limit = int(os.environ.get("PENDING_SUBMISSION_LIMIT", "20"))
        self._local_key: bytes | None = None
        self._queue_key: bytes | None = None

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.inbox_dir, self.attachments_dir, self.wiki_dir, self.data_dir):
            d.mkdir(parents=True, exist_ok=True)
        for sub in ("concepts", "entities", "projects", "sources", "analyses"):
            (self.wiki_dir / sub).mkdir(exist_ok=True)
        self.schema_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.schema_file.exists() and self.schema_builtin.exists():
            self.schema_file.write_text(self.schema_builtin.read_text(encoding="utf-8"), encoding="utf-8")
        index = self.wiki_dir / "index.md"
        if not index.exists():
            index.write_text("# Wiki 索引\n\n（尚无内容）\n", encoding="utf-8")
        log = self.wiki_dir / "log.md"
        if not log.exists():
            log.write_text("# 变更日志\n\n", encoding="utf-8")

    def local_key(self) -> bytes:
        """本地密钥：优先 LOCAL_KEY_FILE（Docker Secret），否则在 data 目录生成并持久化。"""
        if self._local_key is not None:
            return self._local_key
        if self.local_key_file:
            key = self._parse_key_file(Path(self.local_key_file))
        else:
            path = self.data_dir / "local.key"
            if path.exists():
                key = self._parse_key_file(path)
            else:
                key = os.urandom(32)
                path.write_text(key.hex(), encoding="utf-8")
                path.chmod(0o600)
        if len(key) != 32:
            raise RuntimeError("LOCAL_KEY_FILE 必须是 32 字节（hex 64 字符或 base64）")
        self._local_key = key
        return key

    def queue_key(self) -> bytes:
        """待确认队列密钥：PENDING_QUEUE_KEY_FILE 优先；缺失/未配置时回退本地密钥。
        业务代码不依赖任何 Docker 路径/服务名/网络，只读取环境变量指向的文件。"""
        if self._queue_key is not None:
            return self._queue_key
        if self.pending_queue_key_file:
            path = Path(self.pending_queue_key_file)
            if path.exists():
                key = self._parse_key_file(path)
                if len(key) != 32:
                    raise RuntimeError("PENDING_QUEUE_KEY_FILE 必须是 32 字节（hex 64 字符或 base64）")
                self._queue_key = key
                return key
        self._queue_key = self.local_key()
        return self._queue_key

    @staticmethod
    def _parse_key_file(path: Path) -> bytes:
        """读密钥文件：原始 32 字节直接使用（不可 strip，否则会损坏恰以空白字节开头/结尾的密钥）；
        否则按文本（hex/base64，可容忍换行）解析。"""
        raw = path.read_bytes()
        if len(raw) == 32:
            return raw
        return Settings._parse_key(raw)

    @staticmethod
    def _parse_key(raw: bytes) -> bytes:
        if len(raw) == 32:
            return raw
        text = raw.decode("utf-8", errors="ignore").strip()
        if len(text) == 64:
            try:
                return bytes.fromhex(text)
            except ValueError:
                pass
        try:
            decoded = base64.b64decode(text)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        raise RuntimeError("无法解析本地密钥")
