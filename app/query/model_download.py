"""模型下载服务（issue #15）：把 sentence-transformers（HF 模型 ID）权重拉到数据目录持久卷。

下载落在 ``<DATA_DIR>/models/hf/<repo_id>``（docker-compose 已把 ``./data`` 挂为持久卷，
容器重建不丢模型）。任务在独立后台线程执行，HTTP 请求不阻塞；进度（字节/文件/百分比）
可在进程内查询。重复下载幂等：运行中复用任务、已完成直接返回、磁盘已有快照不再起线程。
网络失败给出明确错误 + Ollama 替代路线指引；huggingface_hub 单请求 10s 超时，不挂死。

单实例单进程（与部署约束一致）：任务表存内存，进程重启即清，但快照目录在持久卷上，
重启后按“磁盘已有”幂等路径处理。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from huggingface_hub import snapshot_download

STATUS_UNKNOWN = "unknown"
STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

MODELS_DIR = "models"
HF_SUBDIR = "hf"

OLLAMA_GUIDANCE = "可改用本地 Ollama 路线：先在 Ollama 中执行 `ollama pull <模型名>` 拉取模型，再到设置页选择 Ollama 路线。"


def hf_models_dir(data_dir: Path) -> Path:
    """HF 模型快照根目录（数据目录持久卷）。"""
    return Path(data_dir) / MODELS_DIR / HF_SUBDIR


def model_snapshot_dir(data_dir: Path, model: str) -> Path:
    """单个模型（repo_id）的快照目录；repo_id 允许含 ``/``（org/repo）。"""
    return hf_models_dir(data_dir) / model


def validate_model_id(model: str) -> str | None:
    """校验自定义 HF 模型 ID；非法返回错误文案，合法返回 None。"""
    if not model or model != model.strip():
        return "模型 ID 不能为空"
    if "\x00" in model or "\\" in model or model.startswith("/") or any(ch.isspace() for ch in model):
        return "模型 ID 不合法"
    parts = model.split("/")
    if any(not part or part in {".", ".."} or part != part.strip() for part in parts):
        return "模型 ID 不合法"
    return None


def snapshot_complete(data_dir: Path, model: str) -> bool:
    """快照目录是否已存在完整下载（config.json 为完整性哨兵）。"""
    try:
        return (model_snapshot_dir(data_dir, model) / "config.json").is_file()
    except Exception:
        return False


def friendly_download_error(exc: Exception) -> str:
    """把底层异常映射为面向页面的友好文案；网络失败给出 Ollama 替代路线指引。"""
    name = type(exc).__name__
    detail = " ".join(str(exc).split())[:200] or name
    low = detail.lower()
    if any(word in low for word in ("connection", "timeout", "timed out", "network", "resolve",
                                    "proxy", "offline", "getaddrinfo", "sslerror", "unreachable",
                                    "localentrynotfounderror", "cannot find an appropriate")):
        return f"模型下载失败（网络不可达，{name}）：请检查网络/代理设置后重试。{OLLAMA_GUIDANCE}"
    if any(word in low for word in ("404", "not found", "entry not found", "revision")):
        return f"模型下载失败（模型不存在或 ID 错误，{name}）：请确认模型 ID 后重试。{OLLAMA_GUIDANCE}"
    if any(word in low for word in ("429", "quota", "rate limit")):
        return f"模型下载失败（触发限流，{name}）：请稍后重试。{OLLAMA_GUIDANCE}"
    return f"模型下载失败（{name}）：{detail}。{OLLAMA_GUIDANCE}"


class Job:
    """单个模型的一次下载任务；状态与进度由下载线程更新，读取方加锁。"""

    def __init__(self, model: str):
        self.model = model
        self.status = STATUS_QUEUED
        self.error = ""
        self.files_total = 0
        self.files_done = 0
        self.bytes_total = 0
        self.bytes_done = 0
        self.started_at = time.time()
        self.finished_at: float | None = None

    def snapshot(self) -> dict:
        if self.status == STATUS_DONE:
            progress = 100.0
        elif self.files_total:
            progress = round(100 * self.files_done / self.files_total, 1)
        elif self.bytes_total:
            progress = round(100 * min(self.bytes_done, self.bytes_total) / self.bytes_total, 1)
        else:
            progress = 0.0
        return {
            "model": self.model,
            "status": self.status,
            "downloaded": self.status == STATUS_DONE,
            "progress": progress,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_local = threading.local()


class _Progress:
    """snapshot_download 的 ``tqdm_class`` 替身：把进度聚合到当前线程的任务。

    snapshot_download 会创建三根进度条（Downloading bytes 字节传输 / Reconstructing 磁盘重建 /
    Fetching N files 文件级），全部经此类回调；按 desc 前缀区分，字节与文件进度写入 Job。
    """

    def __init__(self, *args, total=None, desc=None, **kwargs):
        self.n = 0
        self.total = int(total or 0)
        self.desc = str(desc or "")
        self.format_dict: dict = {}
        self._job = getattr(_local, "job", None)
        self._is_transfer = self.desc == "Downloading bytes"
        self._is_files = self.desc.startswith("Fetching")
        if self._is_files and self._job is not None:
            self._job.files_total = max(self._job.files_total, self.total)

    def update(self, n=1) -> None:
        inc = int(n or 0)
        self.n += inc
        job = self._job
        if job is None:
            return
        if self._is_transfer:
            job.bytes_done += inc
            job.bytes_total = max(job.bytes_total, int(self.total or 0))
        elif self._is_files:
            job.files_done = max(job.files_done, self.n)

    def refresh(self) -> None:
        pass

    def close(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def set_description(self, desc=None, refresh=True) -> None:
        self.desc = str(desc or "")

    def set_postfix_str(self, postfix, refresh=False) -> None:
        pass

    def set_postfix(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class DownloadManager:
    """进程内下载任务表：幂等启动、后台线程执行、状态可查。"""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, model: str, data_dir: Path) -> tuple[Job, bool]:
        """幂等启动下载。返回 (job, 是否新启动)。

        运行中/已完成的任务直接复用；磁盘已有完整快照直接返回 done；失败任务允许重试。
        """
        with self._lock:
            existing = self._jobs.get(model)
            if existing is not None and existing.status in {STATUS_QUEUED, STATUS_DOWNLOADING, STATUS_DONE}:
                return existing, False
            job = Job(model)
            self._jobs[model] = job
            if snapshot_complete(data_dir, model):
                job.status = STATUS_DONE
                job.finished_at = time.time()
                return job, False
        thread = threading.Thread(
            target=self._run, args=(model, data_dir), daemon=True, name=f"model-download-{model}"
        )
        thread.start()
        return job, True

    def snapshot(self, model: str) -> Job | None:
        with self._lock:
            return self._jobs.get(model)

    def status_view(self, model: str, data_dir: Path) -> dict:
        """状态查询视图：无任务时按磁盘快照区分 done（此前已下载）与 unknown。"""
        job = self.snapshot(model)
        if job is not None:
            return job.snapshot()
        if snapshot_complete(data_dir, model):
            return {"model": model, "status": STATUS_DONE, "progress": 100.0, "downloaded": True,
                    "files_done": 0, "files_total": 0, "bytes_done": 0, "bytes_total": 0,
                    "error": "", "started_at": None, "finished_at": None}
        return {"model": model, "status": STATUS_UNKNOWN, "progress": 0.0, "downloaded": False,
                "files_done": 0, "files_total": 0, "bytes_done": 0, "bytes_total": 0,
                "error": "", "started_at": None, "finished_at": None}

    def _run(self, model: str, data_dir: Path) -> None:
        with self._lock:
            job = self._jobs.get(model)
        if job is None:
            return
        job.status = STATUS_DOWNLOADING
        _local.job = job
        target = model_snapshot_dir(data_dir, model)
        try:
            snapshot_download(repo_id=model, local_dir=str(target), tqdm_class=_Progress)
        except Exception as exc:
            job.status = STATUS_FAILED
            job.error = friendly_download_error(exc)
        else:
            job.status = STATUS_DONE
            job.files_total = job.files_done
            job.bytes_total = job.bytes_done
        finally:
            job.finished_at = time.time()
            _local.job = None


manager = DownloadManager()
