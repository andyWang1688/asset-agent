"""索引重建服务（issue #16）：保存向量不兼容的检索配置后自动触发后台重建，状态可查询。

重建在独立后台线程执行：先把新索引建到临时 staging 目录，完成后原子换名到正式目录。
重建期间正式目录的旧索引原样保留，问答继续服务；换名窗口极短，查询方遇到索引缺失
时走关键词兜底（见 ``hybrid`` 的降级路径）。与模型下载服务同约束：单实例单进程，
任务表存内存，进程重启即清（索引目录在持久卷上，重启后问答按需自动重建）。
"""

from __future__ import annotations

import shutil
import threading
import time

from . import retrieval

STATUS_IDLE = "idle"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

STAGING_SUFFIX = ".rebuild"


class RebuildJob:
    """一次重建任务；状态由重建线程更新，读取方加锁。"""

    def __init__(self):
        self.status = STATUS_QUEUED
        self.error = ""
        self.pages = 0
        self.embedding = ""
        self.started_at = time.time()
        self.finished_at = None

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "pages": self.pages,
            "embedding": self.embedding,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class RebuildManager:
    """进程内重建任务表：幂等启动、后台线程执行、状态可查询。"""

    def __init__(self):
        self._job: RebuildJob | None = None
        self._lock = threading.Lock()

    def start(self, settings, page: dict | None) -> RebuildJob:
        """幂等启动重建。进行中的任务直接复用；已结束的任务可被再次 start 覆盖重试。"""
        with self._lock:
            if self._job is not None and self._job.status in {STATUS_QUEUED, STATUS_RUNNING}:
                return self._job
            job = RebuildJob()
            self._job = job
        thread = threading.Thread(
            target=self._run, args=(settings, page, job), daemon=True, name="index-rebuild"
        )
        thread.start()
        return job

    def status(self) -> dict:
        with self._lock:
            job = self._job
        if job is None:
            return {
                "status": STATUS_IDLE,
                "pages": 0,
                "embedding": "",
                "error": "",
                "started_at": None,
                "finished_at": None,
            }
        return job.snapshot()

    def _run(self, settings, page, job: RebuildJob) -> None:
        job.status = STATUS_RUNNING
        target = retrieval.index_dir(settings)
        staging = target.with_name(target.name + STAGING_SUFFIX)
        try:
            from . import retrieval_config

            embedder = retrieval_config.build_page_embedder(settings, page)
            result = retrieval.build(settings, embedder, staging=staging)
            # 原子换名：旧索引保留到重建完成的最后一刻，换名窗口内查询走关键词兜底。
            shutil.rmtree(target, ignore_errors=True)
            staging.replace(target)
            job.pages = result["pages"]
            job.embedding = result["embedding"]
            job.status = STATUS_DONE
        except Exception as exc:
            job.status = STATUS_FAILED
            job.error = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
        finally:
            job.finished_at = time.time()


manager = RebuildManager()
