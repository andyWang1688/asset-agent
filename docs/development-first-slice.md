# 首版开发切片：运行与范围

## 运行

### 后端（本地）

在项目根目录（本 worktree 仓库根）运行，使用本仓库虚拟环境（`python3.12`）：

```bash
# 0) 准备环境（首次）：安装依赖到本仓库虚拟环境
uv sync

# 1) 准备数据目录并生成本地密钥（首次）
export WORKSPACE_DIR="$PWD/workspace"
export DATA_DIR="$PWD/workspace/.asset-assistant"

# 2) 配置知识模型与 Vaultwarden（环境变量或设置页）
#    BW_EMAIL / BW_PASSWORD（或 BW_CLIENTID/BW_CLIENTSECRET）
#    VAULTWARDEN_URL（默认 http://127.0.0.1:8081）
#    知识模型：启动后在「设置 → 模型配置」添加并激活 knowledge 角色模型

# 3) 启动后端（仅绑定 127.0.0.1）；Vite dev 前端 5173 需加入允许 Origin
export ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 前端（本地）

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev   # Vite dev server，代理 /api -> http://127.0.0.1:8000
```

打开 `http://127.0.0.1:5173`（dev）。生产部署用 Docker：`docker compose up -d --build`，入口 `http://127.0.0.1:8000`（生产 Nginx 与后端同源，浏览器请求同源 `/api`，无需放行 5173）。

### 同源 / 允许 Origin

后端仅允许 `ALLOWED_ORIGINS` 白名单内的本机来源（写接口校验 Origin/Referer，默认仅 8000）。Vite dev 前端运行在 5173，浏览器对 `/api` 的 Origin 是 5173，因此本地开发需把 5173 加入 `ALLOWED_ORIGINS`（见上），不要通过禁用安全中间件或放行任意 Origin 绕过。

## 生成 OpenAPI 类型（前端）

`pnpm gen:api` 只读取 `frontend/api-schema.json`，不会自行生成它。需先从本仓库 `app` 导出 OpenAPI 再生成：

```bash
# 在仓库根目录，用本 worktree 的 app 导出 schema
python -c "import json; from app.main import app; json.dump(app.openapi(), open('frontend/api-schema.json','w'), ensure_ascii=False)"
cd frontend
pnpm gen:api   # openapi-typescript ./api-schema.json -o ./src/lib/apiTypes.ts
```

## 当前首版范围（已实现）

- 后端 app/wiki/ + app/query/：LLM Wiki 主链路。
  - 问答：WikiQuestionAnswerEngine 用受限工具循环（index/list/read/search-text(BM25)/final），引用只来自真正读到的页面，不依赖向量/embedding/重排。
  - 维护：compiler.compile_source 用同一受限循环先读 index 与相关页面，再产出 final.plan 写页；apply_plan 整体校验路径/动作/重复/内容后统一写入，记录变更与冲突。
  - app/wiki/tools.py：路径白名单 + 内容预算 + 符号链接/越权拒绝；进入模型前按真实安全策略 + 登记引用检查；只读，不写 Raw/Wiki/保险柜/设置，不触网络/shell。
  - app/query/bm25.py：纯 Python BM25，不装载 torch/向量模型。
- 任务结果：tasks.result 记录新增/更新页面与冲突，前端任务详情可点击打开对应 Wiki 页。
- 引用安全：私密引用只信任已确认来源登记元数据，伪造/未知形状不免检；模型入参与输出按实际安全策略扫描。

## 所需依赖

- 后端：`fastapi`、`uvicorn`、`cryptography`、`httpx`、`pyyaml`、`regex`、`pypdf`、`python-multipart`、`reportlab`。主链路（LLM Wiki）不加载 torch / llama_index；legacy 检索/embedding 依赖仅在显式检索设置入口调用时惰性导入。
- 前端：`pnpm` + Node 22；依赖见 `frontend/package.json`。

## 测试替身限制

- 后端单元测试使用 tests.fakes.FakeProvider / SequenceProvider 模拟 LLM 的工具动作序列，不访问真实模型或保险柜。
- 前端组件测试使用 vi.mock('@/lib/api') 模拟后端，不访问真实 API。
- 控制代理已用虚构资料完成真实 DeepSeek 模型烟测与浏览器验收；两者均使用内存保险柜替身，详见 [首版验收记录](verification/first-slice-2026-09-08.md)。

## 暂缓（未做）

UIE-mini、Excel/OCR、多文件批次、完整 Private Raw 生命周期、复杂跨系统回滚、legacy 向量/混合检索依赖彻底删除。
