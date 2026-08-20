"""后台任务循环：待确认提交 TTL 清理、Vaultwarden 待处理队列重试 + Wiki 编译任务执行。
故障策略：秘密原文只存在于加密队列；失败任务可重试；不产生半成品页面；
未通过确认闸门或复扫仍残留 Finding 的来源绝不调用云端模型。
knowledge 模型未配置时编译任务保持 pending（fail-closed，不报错不丢数据）；
security 增强模型（可选）接入编译前复扫，失败时回退本地检测结果。"""
import asyncio
import json
import time
from pathlib import Path

from . import crypto, db
from .config import Settings
from .credentials.base import CredentialError, SecretPayload
from .llm.provider import get_security_provider
from .security import redactor
from .security.detectors import ScanEngine, overlaps
from .security.policy import PolicyStore
from .wiki import compiler


class Worker:
    def __init__(self, settings: Settings, creds, provider_getter, security_provider_getter=None) -> None:
        self.settings = settings
        self.creds = creds
        self.get_provider = provider_getter
        self.get_security_provider = security_provider_getter or (lambda: get_security_provider(settings))
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                db.log_security("worker_error", "worker tick 异常")
            await asyncio.sleep(2)

    async def tick(self) -> None:
        await self._expire_submissions()
        await self._flush_pending()
        await self._process_tasks()

    async def _expire_submissions(self) -> None:
        now = time.time()
        for row in db.list_submissions("waiting"):
            age = now - _parse_time(row["created_at"])
            if age > self.settings.queue_ttl_seconds:
                db.resolve_submission(row["id"], "expired")  # 清除密文
                db.log_security(
                    "submission_expired",
                    f"待确认提交 #{row['id']}（来源哈希 {row['sha256'][:16]}）超过 TTL 已过期销毁",
                )

    async def _flush_pending(self) -> None:
        now = time.time()
        for row in db.list_pending(status="pending"):
            age = now - _parse_time(row["created_at"])
            if age > self.settings.queue_ttl_seconds:
                db.update_pending(row["id"], "expired")
                db.log_security("credential_pending_expired", f"待处理凭证 {row['name']} 超过 TTL 已过期")
                for t in db.tasks_by_source(row["source_id"]):
                    if t["status"] == "credential_pending":
                        db.update_task_status(t["id"], "failed", error="凭证保存超时（TTL）")
                continue
            if age < self.settings.queue_retry_seconds and row["retries"] > 0:
                continue  # 退避：失败后至少等一个重试周期
            try:
                payload = json.loads(crypto.open_sealed(self.settings.local_key(), row["payload"]))
            except Exception:
                db.log_security("credential_pending_corrupt", f"待处理凭证 {row['name']} 无法解密")
                db.update_pending(row["id"], "failed")
                continue
            try:
                await self.creds.create_secret(
                    SecretPayload(name=payload["name"], value=payload["value"], note=payload.get("note", ""))
                )
            except CredentialError:
                db.update_pending_retry(row["id"])
                continue
            db.update_pending(row["id"], "saved")
            if row["source_id"] and not db.pending_by_source_open(row["source_id"]):
                for t in db.tasks_by_source(row["source_id"]):
                    if t["status"] == "credential_pending":
                        db.update_task_status(t["id"], "pending")

    async def _process_tasks(self) -> None:
        provider = self.get_provider()
        if provider is None:
            return  # 未配置模型：任务保持 pending，不报错不丢数据
        for t in db.list_tasks(statuses=("pending", "retry")):
            await self.run_task(t["id"], provider)

    async def run_task(self, task_id: int, provider=None) -> None:
        t = db.get_task(task_id)
        if not t or t["status"] not in ("pending", "retry"):
            return
        if db.pending_by_source_open(t["source_id"]):
            db.update_task_status(task_id, "credential_pending")
            return
        src = db.get_source(t["source_id"])
        if not src:
            db.update_task_status(task_id, "failed", error="来源不存在")
            return
        provider = provider or self.get_provider()
        if provider is None:
            return
        # 确认闸门：未经确认的来源不得进入云端模型
        if not src["confirmed"]:
            db.update_task_status(task_id, "failed", error="来源未经确认，已阻止编译")
            db.log_security("gate_blocked", f"任务 #{task_id} 的来源未通过确认闸门")
            return
        try:
            text = Path(src["path"]).read_text(encoding="utf-8")
        except OSError as e:
            db.update_task_status(task_id, "failed", error=f"读取来源失败: {type(e).__name__}")
            return
        # 编译前复扫：除确认放行区间外残留 Finding → 阻断云端调用
        # （本地检测 + 可选 security 增强层；增强层失败回退本地结果）
        try:
            leftover = await self._leftover_findings(src, text)
        except Exception as e:
            db.update_task_status(task_id, "failed", error="编译前复扫失败，已阻止编译")
            db.log_security("gate_blocked", f"任务 #{task_id} 复扫异常已阻断: {type(e).__name__}")
            return
        if leftover:
            db.update_task_status(task_id, "failed", error="脱敏后仍检测到敏感内容，已阻止编译")
            db.log_security("gate_blocked", f"任务 #{task_id} 复扫发现未处置敏感内容")
            return
        db.update_task_status(task_id, "processing")
        try:
            await compiler.compile_source(self.settings, provider, src, text)
            db.update_task_status(task_id, "done")
        except Exception as e:
            db.update_task_retries(task_id)
            db.update_task_status(task_id, "failed", error=f"{type(e).__name__}: {str(e)[:300]}")

    async def _leftover_findings(self, src, text: str) -> list:
        """复扫（等长屏蔽占位符与文件头）；放行区间（相对落盘原文）之外命中即残留。"""
        policy = PolicyStore(self.settings.policy_file).load()
        engine = ScanEngine(policy, security_provider=self.get_security_provider())
        masked = redactor.mask_placeholders(text)
        # 文件头（来源/哈希注释）不是资料内容：等长屏蔽，避免长文件名/哈希被误判为敏感内容
        idx = masked.find("-->")
        if idx != -1:
            masked = " " * (idx + 3) + masked[idx + 3 :]
        post = await engine.scan_async(masked)
        try:
            allowed = [tuple(s) for s in json.loads(src["allowed_spans"] or "[]")]
        except (json.JSONDecodeError, TypeError):
            allowed = []
        return [f for f in post if not any(overlaps(f.span, s) for s in allowed)]


def _parse_time(s: str) -> float:
    try:
        import datetime

        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return time.time()
