# 知守 Memo · AssetAgent

个人使用、由 AI 维护的知识库。把资料交给维护对话，系统先检查敏感内容，再把处理后的资料整理成互相链接的 Markdown Wiki；需要时，在问答对话里查找答案和出处。

[产品说明](docs/PRODUCT.md) · [1.0.1 发布说明](docs/releases/v1.0.1.md) · [本地开发](docs/development-first-slice.md)

## 如何工作

```text
维护：文字 / 一批文件 → 格式校验与文本提取 → 本地敏感检测
                                          ↓
                         确认模式：双栏审查，确认后创建任务
                         自动模式：按默认决定直接处理
                                          ↓
                         后台计划 → 原件归档 / 保险柜保存 / 脱敏 Raw / Wiki
                         任一步失败：撤销本轮保存，保留失败任务

问答：问题安全检查 → 知识模型读 Wiki 目录 → 按需读页面 / BM25 搜索 → 带出处回答
```

- **问答与维护分开**：新会话选择一次模式，中途不切换；问答不上传文件、不修改 Wiki、不创建任务。
- **确认一次，后台执行**：确认模式先审查本机原文与发送预览，可以保护/取消保护、修改引用名称。点击“确认并开始维护”后立即进入任务页，计划生成也是任务阶段。
- **Wiki 是知识成果**：AI 维护页面、关联、来源、目录和变更日志，应用内只读；修改知识需使用维护对话。
- **不需要检索模型**：主流程不使用向量数据库、Embedding 或重排模型；BM25 是内置文本搜索工具，没有单独设置入口。
- **模型统一配置**：知识模型必配；本机或内网部署的安全模型可选。安全策略只管理检测规则与处理方式。

应用面向本机单用户，后端必须保持单进程。若配置云端知识模型，安全处理后的资料、问题和相关 Wiki 内容会发送到该模型服务；“本地优先”不等于完全离线。敏感识别可能漏检，确认模式也需要用户核对。

> **原件与任务**：上传原件按原始字节归档到 Private Raw；多个附件共用一次审查和一个任务。失败时通过持久化补偿恢复本轮保存；保险柜清理受阻时暂停后续维护，连接恢复后继续清理。图片与 OCR 暂不支持。

## 快速开始

需要 Git、Docker 和 Docker Compose。下面的配置会在本机源码构建镜像，首次构建需要联网和较大的依赖下载；本版本没有发布预构建镜像或桌面安装包。

```bash
git clone https://github.com/andyWang1688/asset-agent.git
cd asset-agent
git checkout v1.0.1
./scripts/setup.sh
docker compose up -d --build
```

1. 打开 **https://127.0.0.1:8081** 注册 Vaultwarden 账号。使用本项目生成的自签证书，需核对并信任本机证书。账号和主密码由你设置，不是 AI 自动生成的默认账号。
2. 把 Vaultwarden 邮箱与主密码写入本机凭证文件，再重启后端。以下交互方式避免把主密码写进 shell 历史：
   ```bash
   bash -c 'umask 077; read -r -p "Vaultwarden 邮箱: " email; read -r -s -p "主密码: " password; printf "\n"; printf "%s" "$email" > secrets/bw_email; printf "%s" "$password" > secrets/bw_password; unset password'
   docker compose restart backend
   ```
3. 打开 **http://127.0.0.1:8000**，在“设置 → 模型配置”添加并激活知识模型；安全模型不是必需项。
4. 在“安全策略”选择处理方式。希望发送前检查内容时，选择**确认模式**；当前默认模式为自动处理。
5. 新建维护对话，输入文字或上传一批文件。确认模式下，审查左右内容后点击“确认并开始维护”；自动模式直接按默认决定处理。
6. 在任务页查看进度和结果。成功后可浏览 Wiki，或新建问答对话提问；失败则按原因在维护对话中重新提交。

Vaultwarden 中的密码、证件等原值由你通过 Vaultwarden 客户端查看。应用中的私密引用只展示定位元数据，不是读取密码的入口。

## 文件要求

文件先校验，合规后才提取文本并进入敏感检查；不是完整还原 Office/PDF 版式。

| 格式 | 支持范围与要求 |
| --- | --- |
| Markdown / TXT | UTF-8 文本；手动输入同样走安全流程，显示为短摘要命名的 `.txt` 资料卡片 |
| Excel `.xlsx` / `.xls` | 全部工作表，含隐藏表；单行、非空、不重复表头，不接受合并单元格；`.xlsx` 不接受图片/图表；不执行公式，`.xlsx` 读公式文本，`.xls` 读已保存结果 |
| CSV | UTF-8、UTF-8 BOM、GB18030；逗号/分号/制表符分隔；表头与各行列数需一致 |
| Word `.docx` | 正文、表格、页眉页脚；拒绝图片、文本框、嵌入对象、未接受的修订；不提取批注/脚注等附属内容；`.doc` 需另存为 `.docx` |
| PDF | 仅纯文本 PDF；拒绝加密文档、扫描页、图片页和无文本页面；保留页码 |

每批最多 20 个文件，总大小默认上限 10 MB；表格最多 200,000 个单元格，提取文本最多 2,000,000 字符。图片与 OCR 暂不支持；同一批不接受重复选择同一文件。

## 资料与安全边界

- 正则、关键词上下文、熵值由程序检测；安全模型可选，只能补充或加严检测，失败时回退程序结果。
- 确认模式每轮都显示双栏审查，即使没有检测到敏感值；自动模式不显示预览，按默认决定执行。
- 保存到 Vaultwarden 的值在 Raw/Wiki 中用 `[🔒 名称](private:引用ID)` 代替；仅脱敏项保留替换标记。取消保护属于明确放行，需要核对其影响。
- 报告名称、说明和模型输出继续接受安全校验；已登记引用不含原值。程序检测不代表能保证零遗漏。
- 确认前，提取文本与上传原件一起加密暂存；拒绝或过期时销毁本次暂存。确认后才归档原件，手动文字不额外生成原件。
- Wiki 模型没有原件/保险柜原值读取工具，不执行资料中的命令；对话删除不删除已形成的知识。
- 任务没有重试、取消或删除按钮。失败补偿只删除本轮新建的保险柜条目与文件，并恢复旧 Wiki 和来源记录；复用的历史条目与原件不删除。补偿记录保留到清理成功，应用重启会先恢复未完成事务。

## 数据目录与备份

Docker Compose 默认位置：

```text
workspace/
├── private_raw/     # 未脱敏的上传原件，知识模型不读取
├── raw/inbox/       # 安全处理后的提取文本，不是上传文件的原始二进制
├── wiki/            # Markdown 知识页、index.md、log.md
└── schema/AGENTS.md # Wiki 编写规则

data/               # SQLite、策略、索引及加密事务补偿日志
secrets/            # 本地加密密钥、保险柜登录配置、受信任 CA
certs/              # 本地 TLS 证书与私钥
Docker 卷 vw-data   # Vaultwarden 数据（实际卷名通常带 Compose 项目前缀）
```

非 Docker 运行时，`DATA_DIR` 默认是 `workspace/.asset-assistant`，以运行配置为准。通用设置显示实际运行路径。Docker 中的 `/app/workspace/private_raw` 对应仓库的 `workspace/private_raw`；应用没有原件浏览/下载接口。

备份需包含 `workspace/`、`data/`、`secrets/`、`certs/` 以及 Vaultwarden 的加密备份。建议先停应用写入再复制数据目录；运行中的 SQLite 使用一致性备份方法，不要只复制主数据库而遗漏 WAL。备份应加密，密钥遗失会导致加密配置/队列不可恢复。

**不要删除 SQLite 后仅靠 Markdown“恢复全部数据”**：Markdown 可以重建知识索引，但恢复不了会话、任务、模型配置和私密引用登记。任何清理脚本都应先阅读其范围，尤其保险柜清理可能影响应用创建的真实条目，不属于升级步骤。

## 部署与开发

- Web 入口仅绑定 `127.0.0.1:8000`，Vaultwarden 仅绑定 `127.0.0.1:8081`；后端只在 Docker 内网暴露。
- 不要改为公网监听，不要增加后端 worker 或副本；应用不是多用户服务。
- 用户数据、密钥、证书不随 Git 或 Release 分发。
- 依赖中仍保留旧检索相关包，当前 Wiki 主流程不加载这些模型；暂不等于安装体积已完全轻量化。

```bash
# 后端（Python 3.12，项目虚拟环境）
uv sync --frozen
.venv/bin/python -m pytest -q
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://127.0.0.1:5173 \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（另开终端，Node 22 + pnpm 11.7.0）
cd frontend
pnpm install --frozen-lockfile
pnpm dev
# 检查：pnpm test && pnpm typecheck && pnpm lint && pnpm build
```

本地开发入口是 `http://127.0.0.1:5173`。不要同时启动占用 8000 端口的 Docker 前端和本地后端。

### 主要配置

| 变量 | 用途 |
| --- | --- |
| `WORKSPACE_DIR` / `DATA_DIR` | Wiki/Raw 与运行数据目录 |
| `PRIVATE_RAW_DIR` | 原件目录，默认 workspace/private_raw；须与 Raw/Wiki 分开 |
| `LOCAL_KEY_FILE` / `PENDING_QUEUE_KEY_FILE` | 本地配置/待确认文本加密密钥；支持原始 32 字节、64 字符 hex 或解码为 32 字节的 base64 |
| `POLICY_FILE` | 安全策略文件 |
| `VAULTWARDEN_URL` | 保险柜服务地址，Compose 使用内网 HTTPS |
| `BW_EMAIL` / `BW_PASSWORD` | 保险柜邮箱和主密码，可用对应 `_FILE` 注入 |
| `MAX_UPLOAD_MB` | 每批文件总大小上限，默认 10 MB |
| `HTTP_TIMEOUT` | 模型请求超时秒数，默认 180 |
| `CHAT_MEMORY_ROUNDS` | 问答历史轮数，默认 6 |
| `ALLOWED_ORIGINS` | 浏览器访问白名单，开发模式需加入 5173 |

不需要配置 Embedding、重排或向量库。
