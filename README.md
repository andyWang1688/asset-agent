# AssetAgent · 资产 Agent

> **AssetAgent is a local-first personal asset knowledge agent.** It collects asset documents through chat, gates every sensitive finding behind a human confirmation step, stores credentials exclusively in Vaultwarden, compiles sanitized sources into a structured Markdown Wiki, and answers natural-language questions over it. Single-user, localhost-only, no vector database — and secret plaintext never reaches any LLM.

个人资产智能体：把资料扔进输入框，系统自动 识别并隔离秘密 → 确认闸门逐项裁决 → 凭证存入 Vaultwarden / PII 仅脱敏 → 后台编译成结构化 Markdown Wiki → 之后用自然语言问答找回。

```text
粘贴/上传资料 ──▶ 本地扫描(正则→上下文→熵) ──▶ 确认闸门(逐项裁决)
                      │                            │
                      │                  凭证 ──▶ Vaultwarden（仅引用回写）
                      │                  PII  ──▶ [REDACTED:rule]
                      ▼                            ▼
              自然语言问答 ◀── RAG ── Wiki ◀── 后台 Worker 编译（云端模型只见脱敏文本）
```

- 单用户、本机 Web + Docker；无多用户、无公网暴露、无密码原文读取、无向量库
- **安全不变量**：秘密原文不进入 LLM 请求/响应、Wiki、对话记录、日志
- 模型在「设置」页按角色配置（DeepSeek / GLM / OpenAI / Claude / 通义 / Kimi / 任意 OpenAI 兼容端点），换模型不改代码：
  - **知识库（knowledge，必配）**：统一负责 Wiki 编译与知识问答；未配置/未激活时禁止提交编译任务、禁止发起问答（fail-closed，UI 明确提示）；每角色至多激活一个
  - **安全增强（security，可选）**：接入本地检测管线之后，只能新增或加严识别结果，失败自动回退本地检测；默认仅允许 localhost/内网端点，发送内容先做等长掩码脱敏
- 对话历史按会话分组（DeepSeek 式：日期分组 / 置顶 / 重命名 / 删除），会话视图消息流滚动、输入框钉底

## 快速开始

```bash
./scripts/setup.sh                 # 生成本地密钥（含待确认队列密钥）、自签 TLS 证书与 .env
docker compose up -d --build       # 启动 frontend（Nginx，127.0.0.1:8000）+ backend + vaultwarden
```

1. 创建 Vaultwarden 账号（二选一）：
   - 打开 http://127.0.0.1:8081 网页注册（推荐，密钥派生由官方客户端完成）
   - 自动化：`python scripts/register_vaultwarden_account.py <邮箱> <主密码> https://127.0.0.1:8081`
2. 把账号写进凭证文件（两种方式二选一）：
   ```bash
   # 主密码方式
   printf 'your@email.com' > secrets/bw_email
   printf '你的主密码' > secrets/bw_password
   # 或 API Key 方式（在 Vaultwarden 网页端“账户设置→安全→密钥”创建）
   printf 'user.xxx' > secrets/bw_clientid
   printf 'xxx' > secrets/bw_clientsecret
   docker compose restart backend
   ```
3. 打开 http://127.0.0.1:8000 →「设置」页添加模型（预设自动填充 API 地址与模型名，填 Key 即可；「知识库」角色必配并激活，「安全增强」角色可选）
4. 「对话」页（收集资料模式）粘贴/上传资料（Markdown / TXT / PDF，PDF 仅支持可提取文本）
5. 识别到敏感信息时进入确认闸门逐项裁决（存入 Vaultwarden 并脱敏 / 仅脱敏 / 误报放行），确认后任务进入队列
6. 「任务」页看到 `done` 后，「知识库」页浏览资产页，「对话」页（询问知识模式）提问

> 说明：Vaultwarden 在 Compose 内以自签证书提供 HTTPS（`certs/` 由 setup.sh 生成，bw CLI 强制 HTTPS），
> CA 经 `secrets/ca.crt` 注入 backend 容器信任；Vaultwarden 对外仍只绑定 127.0.0.1。
> 浏览器只访问 `http://127.0.0.1:8000`（frontend/Nginx），`/api/*` 由 Nginx 同源反向代理到 backend 容器（backend 不映射宿主机端口）。

## 目录结构

```text
frontend/               # React 19 + TypeScript + Vite 6 + Tailwind 4 + Radix（独立构建/独立容器）
├── src/                #   features/chat|wiki|tasks|settings、components/ui、hooks、lib(api/markdown/types)
├── nginx.conf          #   SPA 托管 + /api 反向代理到 backend
└── Dockerfile          #   多阶段构建（node → nginx）
app/                    # FastAPI 纯 API 后端（ingest / 确认闸门 / worker / wiki / 安全管线）
workspace/
├── raw/inbox/          # 脱敏后的来源副本（秘密已是 [SECRET_REF:xxx]，PII 是 [REDACTED:rule]）
├── wiki/               # AI 维护的知识页（事实源，可人工编辑、Git 版本化）
│   ├── index.md / log.md
│   └── concepts|entities|projects|sources|analyses/
├── schema/AGENTS.md    # Wiki 维护规则（也作为编译系统提示词）
└── .asset-assistant/   # SQLite（派生索引，可删库从 Markdown 重建）+ config/policy.yaml（安全策略）
assetagent-architecture.html  # 架构总图（本地安全知识编译架构）
```

## 安全设计

| 环节 | 措施 |
|---|---|
| 输入扫描 | 内存先扫描、后持久化：正则（可在 `app/security/rules.py` 追加规则）+ 上下文关键词 + Shannon 熵，统一 Finding（credential / pii / unknown_suspect），按 span/类别合并去重，后层只新增或加严 |
| security 增强检测 | 可选模型接入本地检测（Regex → Context → Entropy）之后：只能新增或加严 Finding（合并只取最高类别/置信度），失败/超时/非法输出一律回退本地检测结果；仅允许 localhost/内网本地端点（禁止公网调用、无放开开关；域名不按后缀直通，一律解析并要求全部结果为本地地址），发送内容先经等长掩码脱敏，绝不把未脱敏输入发给公网模型 |
| knowledge 必配闸门 | 知识库模型未配置/未激活时：`/api/ingest` 拒绝提交（不落盘、不建任务）、确认接口在创建任务前拒绝（待确认记录保留，配置后重试）、`/api/query` 拒绝提问、Worker 不消费任务（保持 pending），UI 在输入/问答/设置页明确提示 |
| 模型角色约束 | 每角色至多一个激活由 `model_configs(role) WHERE is_active=1` 部分唯一索引 + 单事务原子切换共同保证（切换瞬间不存在双激活窗口） |
| 确认闸门 | 发现 Finding 即进入一次性确认页：按类别汇总、规则/置信度/建议动作、掩码上下文、完整脱敏预览；逐项裁决（存 Vaultwarden 并脱敏 / 仅脱敏 / 误报放行）；有未处置 Finding 时拒绝确认，绝不调用云端模型 |
| 安全策略 | `data/config/policy.yaml`（设置页读写，Wiki LLM 只读注入）：闸门模式、禁用内置规则、自定义正则（长度/输入长度/执行时间受限，validator 仅内置白名单）、熵参数、类别默认动作；策略与审计不得含秘密 |
| 秘密隔离 | credential 仅写入 Vaultwarden（幂等：同名同来源条目复用）；PII/疑似项仅脱敏为 `[REDACTED:rule]`；Wiki/对话只保留 `[SECRET_REF:name]` 与元数据；业务层无读取秘密原文的接口 |
| Vaultwarden 故障 | 任务挂起（credential_pending），秘密原文仅以 AES-GCM 密文进入 `pending_secrets` 队列（TTL 7 天，密钥来自 `secrets/local.key`），后台自动重试，成功前不调用云端模型 |
| 待确认队列 | 等待确认期间原文以 AES-256-GCM 加密暂存（密钥 `PENDING_QUEUE_KEY_FILE`，未配置回退 local.key），TTL 7 天自动销毁；取消/过期清除密文；成功后仅保留脱敏 Raw、原文哈希与 secret_ref |
| 编译前复扫 | Worker 编译前对 Raw 复扫（放行区间除外），残留 Finding 阻断云端调用；未经确认的来源一律不编译 |
| 模型响应 | 返回浏览器前再次扫描，命中片段删除并记安全事件；问题中的凭证信息直接拦截；原文不入日志 |
| 文档注入 | 资料一律视为数据：不改变系统规则、不执行命令、不触发外部操作 |
| 模型 API Key | 页面配置后 AES-GCM 加密落 SQLite，接口不回显 |
| 部署 | frontend 只绑定 127.0.0.1:8000；backend 不映射宿主机端口（仅 Docker 内网）；vaultwarden 只绑定 127.0.0.1:8081；Nginx 同源代理并透传 Origin/Referer，写接口拒绝跨源请求（CSRF 防护）；凭证与密钥经宿主机受限文件挂载（`secrets/` 目录，勿提交 Git） |
| 运行模型 | **单进程/单副本**（uvicorn 无 `--workers`）：确认闸门与落盘互斥为进程内锁；两阶段落库（`confirmed=0` 占位经 `sources.sha256 UNIQUE` 抢占，先于凭证写入），重复确认幂等返回、崩溃遗留占位 10 分钟后自动复用；跨进程并发时 Vaultwarden 写入仍无分布式锁，禁止多 worker/多副本部署 |

## 备份

`workspace/`（Wiki + Raw 索引 + SQLite）为普通文件，直接复制即可；SQLite 损坏时删除 `data/app.db*` 后重启，可从 Markdown 重建索引（设置页「重建索引」或 `POST /api/wiki/rebuild`）。
Vaultwarden 数据在卷 `vw-data` 中：备份时用其自带的导出（加密导出），不要直接复制卷文件；备份盘应加密。

> ⚠️ 运行中的 SQLite 禁止跨进程直连：`data/app.db` 处于 WAL 模式，若用宿主机 `sqlite3`/Python 直接打开运行中的库（或不同 SQLite 版本交叉访问），可能损坏 WAL。巡检/备份请先停容器，或改走只读 API（`/api/health`、`/api/tasks`、`/api/security/events` 等）。

> ⚠️ 密钥文件格式：`local.key` / `queue.key` 只接受两种格式——原始 32 字节，或 64 字符 hex（可带末尾换行）。原始 32 字节不做任何 trim（首尾为空白字节的随机密钥同样有效），请勿用会加 BOM/换行的工具生成原始格式。

## 清理演示数据

联调/验收产生的测试产物（mock Wiki 页、Raw 副本、待确认提交、Vaultwarden 测试条目）可用脚本清理：

```bash
scripts/cleanup_demo_data.sh                     # 预览将执行的操作
scripts/cleanup_demo_data.sh --yes               # 执行（文件 + 待确认提交 + 索引重建）
scripts/cleanup_demo_data.sh --yes --vaultwarden # 同时删除 Vaultwarden 中本应用创建的条目（需主密码方式登录）
```

`--vaultwarden` 通过容器内官方 bw CLI 操作，仅匹配 note 以「由资产 Agent 自动保存」（兼容旧版「由资产助手自动保存」）开头的条目；API Key 登录方式请手工清理（http://127.0.0.1:8081），或重置 `vw-data` 卷（先做加密导出备份）。

## 本地开发

```bash
# 后端（使用项目 .venv，勿用全局 Python）
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
python -m pytest                 # 单测/集成（Fake LLM / Fake bw）
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://127.0.0.1:5173 uvicorn app.main:app --reload   # http://127.0.0.1:8000

# 前端（Vite dev server 将 /api 代理到本机 FastAPI）
cd frontend
pnpm install
pnpm dev                         # http://127.0.0.1:5173
```

> 说明：本地前端开发时浏览器 Origin 为 `http://127.0.0.1:5173`，需通过 `ALLOWED_ORIGINS` 加入白名单；
> 生产部署（Docker）无需该配置——浏览器始终同源访问 `http://127.0.0.1:8000`（Nginx 代理）。

联调模型可先不起真实 Key：`uvicorn tools.mock_llm:app --port 9001`，在设置页把 API 地址填 `http://127.0.0.1:9001/v1`（Docker 内填 `http://host.docker.internal:9001/v1`）。Mock 服务同时支持知识库（编译/问答）与安全增强（对 `mocksecret` 报一条增强 Finding）两个角色。

## 前端工程命令

```bash
cd frontend
pnpm install                    # 安装依赖
pnpm dev                        # 本地开发（/api 代理到 127.0.0.1:8000）
pnpm lint                       # ESLint
pnpm typecheck                  # tsc --noEmit
pnpm test                       # Vitest（Markdown URL 白名单 / API 错误解析）
pnpm build                      # 生产构建（dist/）
pnpm gen:api                    # 由 FastAPI OpenAPI 重新生成 src/lib/apiTypes.ts
```

## 环境变量

| 变量 | 说明 |
|---|---|
| `WORKSPACE_DIR` / `DATA_DIR` | 工作区 / 数据目录 |
| `LOCAL_KEY_FILE` | 本地密钥文件（32 字节 hex） |
| `PENDING_QUEUE_KEY_FILE` | 待确认队列 AES-256-GCM 密钥文件（缺省回退 `LOCAL_KEY_FILE`；支持 `_FILE` 间接层） |
| `POLICY_FILE` | 安全策略文件路径（默认 `<DATA_DIR>/config/policy.yaml`） |
| `PENDING_SUBMISSION_LIMIT` | 待确认提交上限（默认 20） |
| `VAULTWARDEN_URL` | Vaultwarden 地址 |
| `BW_EMAIL` / `BW_PASSWORD` | Vaultwarden 主密码登录（或 `BW_CLIENTID` / `BW_CLIENTSECRET` API Key 登录） |
| `HTTP_TIMEOUT` `MAX_UPLOAD_MB` `QUEUE_TTL_SECONDS` `QUEUE_RETRY_SECONDS` | 模型超时 / 上传上限 / 队列 TTL / 重试周期 |

以上均支持 `_FILE` 后缀（如 `BW_PASSWORD_FILE=/run/secrets/bw_password`，Docker Secret 方式）。

## API 摘要

`POST /api/ingest`（文本/文件，可能返回待确认提交）· `GET/POST /api/pending/submissions[/{id}]` + `/{id}/confirm` + `/{id}/cancel`（确认闸门）· `POST /api/query`（支持 `session_id` 归组会话）· `GET /api/chat/history`（按会话返回 title/pinned）· `POST /api/chat/session/title|pin|adopt` · `DELETE /api/chat/session` · `GET /api/wiki/*` · `GET /api/tasks` + `POST /api/tasks/{id}/retry` · `GET /api/secrets`（仅元数据）· `GET/POST /api/settings/models`（按角色：knowledge 必配 / security 可选增强）· `GET/POST /api/settings/policy`（安全策略）· `GET /api/security/events`
