# 前端交接文档（给接手者：opencode）

> 目标：把「资产 Agent」前端按新设计稿 `~/Downloads/asset-assistant-redesign.html` 重构，并保证真实功能可用。
> 当前状态：重构已完成三轮迭代（设计稿落地 → 流式标题/断点修复 → token 体系化重构），但用户对最终视觉效果仍不满意（**最后一次反馈未给出具体问题点**），由接手者继续。

---

## 1. 背景与目标

- 项目：个人资产 Agent（AssetAgent；对话收集资产资料 → 脱敏确认 → 后台编译 Wiki → 问答检索）。
- 新设计稿：`/Users/wangxinxin/Downloads/asset-assistant-redesign.html`（单文件 HTML 原型，oklch 色板、细边框、mono 元信息标签、轻动效）。
- 用户要求：页面样子按新设计稿，技术栈不变，功能（真实后端 API）不能丢。

## 2. 技术栈（不要变）

| 项 | 值 |
|---|---|
| 框架 | React 19 + TypeScript 5.8（strict，含 noUnusedLocals/Parameters） |
| 构建 | Vite 6 + Tailwind CSS 4（@tailwindcss/vite 插件） |
| 组件 | Radix primitives + shadcn 风格封装（`src/components/ui/`） |
| 包管理 | pnpm 11 |
| 目录 | `frontend/` |

## 3. 访问入口与部署拓扑（容易踩坑）

- **用户日常入口：`http://127.0.0.1:8000`** —— Docker nginx（容器 `asset-assistant-frontend`），是项目唯一对宿主机暴露的端口，`/api` 反代到 backend 容器。
- **`http://127.0.0.1:5173`** 只是 Vite dev server（代理 `/api` → `127.0.0.1:8000`）。**不要让用户看 5173 当验收**。
- 部署新前端：
  ```bash
  cd /Users/wangxinxin/work/projects_pycharm/ai-asset-assistant
  docker compose up -d --build frontend
  ```
  （只重建 frontend；backend / vaultwarden 容器不要动。）
- 前端代码在 `frontend/`，Dockerfile 在 `frontend/Dockerfile`（node:22-alpine 构建 + nginx:1.27 托管）。
- `frontend/nginx.conf`：index.html 禁缓存、带 hash 静态资源 30 天缓存；`/api` 代理带 Origin/Referer 透传与 600s 超时。

## 4. 当前架构（已完成的重构）

### 4.1 三层结构
1. **Token 层**：`frontend/src/index.css` 的 `@theme`（唯一来源）。语义色（bg/surface/fg/muted/border/border-strong/soft/accent/danger/ok/warn）、圆角 6 档（5/7/10/14/16/pill）、字号 5 档（meta/caption/body/input/panel）、阴影 2 档、统一缓动。设计约束：**全站边框恒为 1px，强调只靠颜色深浅**。
2. **组件层**：`src/components/ui/` —— `button.tsx`（primary/outline/ghost/compact/danger/link）、`badge.tsx`（accent/muted/ok/warn/err）、`card.tsx`（Card/CardHeader/CardTitle/CardBody/Row/Empty）、`input.tsx`、`textarea.tsx` 为本轮统一体系；sheet/alert-dialog/dropdown-menu/select/tooltip 等为 shadcn 遗留（可用，部分仍用旧别名如 `text-muted-fg`，@theme 里有别名映射，可继续统一）。
3. **页面层**：`src/features/` 四页 + `src/components/` 外壳，全部只引用 token/组件。

### 4.2 文件地图
| 文件 | 职责 |
|---|---|
| `src/index.css` | token + base + 动画 + md-body + 响应式 |
| `src/App.tsx` | 四个 `.view` 分节切换 |
| `src/components/app-shell.tsx` | 218px 侧栏 + 顶栏 + 内容页；移动端底部导航 |
| `src/components/app-sidebar.tsx` | AA 品牌 / 导航分组 / 任务计数 / 本地模式页脚 / MobileBottomNav |
| `src/components/history-panel.tsx` | 对话历史滑入面板（`/api/chat/history`） |
| `src/features/chat/chat-page.tsx` | 模式切换、流式标题（useTypewriter）、任务抽屉（接收→识别→归类→编译）、提示词 chips、待确认提交列表 |
| `src/features/chat/composer.tsx` | 输入区（附件 + 发送） |
| `src/features/chat/message-list.tsx` | 问答气泡 + 引用跳转 |
| `src/features/chat/confirm-sheet.tsx` | 敏感信息确认闸门（真实裁决流程，勿删功能） |
| `src/features/wiki/wiki-page.tsx` | wiki 导航树 + 阅读器（搜索/折叠/重建索引） |
| `src/features/tasks/tasks-page.tsx` | 状态 chips、任务队列、图例弹层、分页、重试、最近完成 |
| `src/features/settings/settings-page.tsx` | 模型配置 / 高级安全策略 / 安全事件 |
| `src/features/settings/model-sheet.tsx` | 模型添加/编辑表单 |
| `src/hooks/` | use-chat / use-tasks / use-wiki / use-submissions / use-models / use-is-mobile / use-typewriter |
| `src/lib/api.ts` | 全部后端调用集中于此（别在组件里散落 fetch） |
| `src/lib/types.ts` / `apiTypes.ts` | 类型（apiTypes 由 `pnpm gen:api` 生成） |

### 4.3 关键实现点
- **流式标题**：`use-typewriter.ts` 逐字打字 + `.streaming::after` 光标；`prefers-reduced-motion` 直接显示全文；切换模式/重新进对话页重播（chat-page 的 `playKey`）。
- **断点唯一 820px**：`useIsMobile(820)` 与 CSS `@media (max-width:820px)` 必须一致（曾因 900 vs 820 打架导致样式乱）。
- **老浏览器降级**：`vite.config.ts` 的 `css.transformer: 'lightningcss'` + targets（Safari 15.4 / Chrome 100）把 oklch/color-mix 降级为 `@supports` 渐进增强（静态 rgb 兜底），已验证构建产物正确。
- **pnpm 特殊**：仓库有 supply-chain 校验，跑脚本必须加参数：
  ```bash
  cd frontend
  pnpm --config.verify-deps-before-run=false run typecheck   # tsc
  pnpm --config.verify-deps-before-run=false run build       # tsc + vite build
  pnpm --config.verify-deps-before-run=false run lint        # eslint（现 0 error，12 条 fast-refresh warning 为存量）
  pnpm --config.verify-deps-before-run=false run test        # vitest
  pnpm --config.verify-deps-before-run=false run dev         # dev server
  ```

## 5. 用户反馈历史（逐轮，接手前务必先读）

1. **"页面空白/打不开"** → 根因：用户入口是 8000（docker），不是 5173；且 5173 的 dev server 曾被关闭。教训：**验收一律用 8000**，dev server 只是开发用。
2. **"标题不流式、样式乱、不自适应"** → 两个根因：① 设计稿标题是打字机流式，当时未实现（已补）；② React 移动断点 900 与 CSS 820 不一致，821–900px 窗口混搭布局（已统一为 820，并补了移动端底部 padding）。
3. **"每个页面样式不一样、边框有宽有窄"** → 根因：设计稿 CSS 类、Tailwind 工具类、shadcn 组件三套体系并存。已重构为 token + 统一组件三层结构；实测全站边框只有 1px 一种宽度、圆角/字号均命中 token 档位。
4. **最后一轮："还是问题"（未具体化）** → **接手第一件事：请用户提供具体现象**（哪一页/什么元素/浏览器与版本/截图），不要盲改。可能方向：具体间距/字号观感、某浏览器表现、动效节奏等主观视觉问题；也可能用户对整体风格另有想法，需先对齐。

## 6. 验证方法（接手后自测）

- 构建四件套见 4.3。
- 部署后浏览器验证（ego-browser 可用，Chromium）：
  - 打开 `http://127.0.0.1:8000/`，确认侧栏/顶栏/对话页渲染、控制台无报错。
  - 多宽度溢出检测（8 档：1440/1024/900/860/820/768/480/375），`document.documentElement.scrollWidth - clientWidth` 应为 0。
  - 一致性审计：扫描各页元素的 computed style，边框宽度应只有 `1px`，圆角应只有 5/7/10/14/16/999px，字号应只有 token 档位。
- 功能冒烟：流式标题（切模式看逐字+光标）、wiki 树点开文档、任务页图例/重试、设置页三段+策略展开+添加模型下拉、历史面板列表/详情、收集模式任务抽屉（真实提交会写后端数据，慎用）。
- `workspace/redesign-shots/` 是重构前的旧截图，已过时，勿参考。

## 7. 已知遗留（可选清理）

- `src/components/ui/` 下 sidebar/resizable/scroll-area/collapsible/switch/separator/tooltip/label/skeleton 可能已无引用（保留无害，删除前 grep 确认）。
- sheet/alert-dialog/dropdown-menu/select 等 shadcn 组件内部仍用旧别名类（@theme 有映射，视觉一致），若要彻底统一可把 `text-muted-fg`→`text-muted`、`bg-fill`→`bg-soft`、`text-primary`→`text-fg` 替换。
- 任务抽屉用 `grid-template-rows: 0fr→1fr` 动画，Chrome 有约半秒延迟才启动（设计稿同款机制），如需更即时可换 max-height 动画。
