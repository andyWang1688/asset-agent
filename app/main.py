"""AI 资产助手入口：单容器纯 API 服务 + 后台 Worker。
仅绑定容器内网（由前端 Nginx 同源反向代理 /api/*）；严格限制 Origin/CORS，
写接口拒绝跨源请求（CSRF 防护）。前端由 frontend/ 独立构建与托管。"""
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db
from .api import router
from .config import Settings
from .credentials.vaultwarden import VaultwardenAdapter
from .llm.provider import get_active_provider, get_security_provider
from .security.policy import PolicyStore
from .worker import Worker

_DEFAULT_ORIGINS = (
    "http://127.0.0.1:8000,http://localhost:8000,https://127.0.0.1:8000,https://localhost:8000"
)
_ALLOWED_ORIGINS = {
    o.strip().rstrip("/")
    for o in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
}
# Referer 回退校验：hostname 必须精确等于本机地址（禁止前缀匹配，防 127.0.0.1.evil.com 类绕过）
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    settings.ensure_dirs()
    db.init(settings.data_dir / "app.db")
    creds = VaultwardenAdapter(settings)
    policy_store = PolicyStore(settings.policy_file)
    policy_store.load()  # 启动即校验一次：损坏文件回退默认策略

    def get_provider():
        # knowledge 角色（默认）：Wiki 编译 + 知识问答；未配置时提交/提问被 API 与 Worker 阻断
        return get_active_provider(settings)

    def get_sec_provider():
        # security 角色（可选增强检测）；端点策略不满足视为未配置
        return get_security_provider(settings)

    worker = Worker(settings, creds, get_provider, get_sec_provider)
    worker.start()
    app.state.ctx = SimpleNamespace(
        settings=settings, creds=creds, worker=worker, get_provider=get_provider,
        get_security_provider=get_sec_provider, policy_store=policy_store
    )
    yield
    await worker.stop()


app = FastAPI(title="AI 资产助手", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    """严格限制 Origin/CORS：
    - 携带 Origin 的请求必须是本机白名单来源（浏览器跨源读写均被拒绝）；
    - 写方法在无 Origin 时校验 Referer 的 hostname（精确等于 127.0.0.1/localhost，
      防 127.0.0.1.evil.com 类前缀绕过），即 CSRF 防护。
    本产品无登录、仅绑定 127.0.0.1，同源即本机页面。"""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in _ALLOWED_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "跨源请求被拒绝（Origin 不允许）"})
    if request.method in _UNSAFE_METHODS and not origin:
        referer = request.headers.get("referer") or ""
        if referer:
            try:
                host = (urlsplit(referer).hostname or "").lower()
            except ValueError:
                host = ""
            if host not in _ALLOWED_HOSTS:
                return JSONResponse(status_code=403, content={"detail": "跨源请求被拒绝（Referer 不允许）"})
    return await call_next(request)
