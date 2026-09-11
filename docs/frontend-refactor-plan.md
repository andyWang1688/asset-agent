# 前端重构方案（2026-09 设计冻结版）

> 设计基准：本次重构的视觉与交互以冻结 demo 为准（本地 demo：`/tmp/opencode/shadcn-demo/layout-demo`，含字标与全部页面）。
> 原则：不迁移旧设计 token 与自研组件；功能、接口、URL 结构与数据语义保持不变；只重写 UI 层。

## 1. 技术基座

| 项 | 结论 |
| --- | --- |
| 组件底座 | shadcn（Radix base，使用合并包 `radix-ui`） |
| 风格 | Maia（组件密度/圆角/间距以 Maia 组件代码为准） |
| 主题 | neutral（黑白中性），无品牌主色 |
| 字体 | Figtree Variable（`@fontsource-variable/figtree`） |
| 图标 | lucide（保留现有依赖；官方组件内的 hugeicons 一律替换为 lucide） |
| 动效 | `tw-animate-css` + 少量自定义（滑动胶囊按测量实现）；尊重 `prefers-reduced-motion` |
| 深色 | 支持 `.dark`，跟随系统/手动切换 |

## 2. 场景色规范（无主题色）

| 场景 | 颜色 |
| --- | --- |
| 发送、确认等需要用户注意的动作 | 唯一填充按钮；发送=黑，确认=绿（emerald-600） |
| 常规动作（保存/测试/编辑/添加/刷新） | outline / ghost，不填充 |
| 已激活 / 已就绪 | 绿色图标 + 文字 |
| 必配未配置 | 红色警示图标 + 文字 |
| 可选未配置 | 琥珀警示图标 + 文字 |
| 开关 / 单选选中 | 绿色（`data-[state=checked]:bg-emerald-600` / `accent-emerald-600`） |
| 任务状态 | 处理中=灰+慢速旋转，成功=绿，失败=红，待确认=琥珀 |
| 标签（必配/可选/版本） | 描边 Badge，不填充 |

## 3. 页面结构

- **外壳**：单侧栏（GPT 式）。品牌字标 → 新对话 → 工作区导航（对话/知识库/任务/设置）→ 可折叠对话历史（今天/昨天/更早，行内 DropdownMenu：重命名/置顶/删除）。收起为图标态（历史隐藏，品牌变「守」字标）。移动端为 Sheet 抽屉。
- **对话**：空状态（模式滑动胶囊在输入框内、问候语、2×2 建议卡）；消息（用户=浅灰气泡，助手=纯文本；维护报告=卡片；思考中=跳动点）；输入区单层圆角容器；确认闸门=Sheet；私密引用=Sheet。
- **知识库**：左目录（搜索 + 分类折叠）+ 右正文（排版容器），无「重建索引」按钮（索引随维护任务自动重建）。
- **任务**：运行记录表（状态筛选滑动胶囊 + 搜索 + 刷新图标按钮）；行内展开详情（高度动画），无抽屉。
- **设置**：模块滑动胶囊（模型配置/检索配置/安全策略/安全事件/关于）+ 分组行式布局（标签左、控件右）；模型编辑 Sheet；删除模型 AlertDialog；关于页含字标、定位句、版本、数据目录、保险柜状态。

## 4. 组件映射（旧 → 新）

| 旧 | 新 |
| --- | --- |
| `components/layout/*`（PageShell/SectionCard/FormRow/SegmentedControl/NavHighlight/EmptyState/LoadingState/TableSkeleton/DocSkeleton/PageTransition） | 删除；页面直接用 shadcn `Card`、自定义 `SegmentedTabs`、`Empty`、`Skeleton`、`animate-in` |
| `components/history-panel.tsx` | 删除；历史并入 `app-sidebar` |
| `components/ui/button-variants.ts`（自定义 primary/compact/danger） | 官方 Button variants |
| `components/ui/badge.tsx`（自定义 ok/warn/err/muted） | 官方 Badge + 场景色 class |
| 自研拖拽侧栏宽度 `lib/sidebar-width.ts` + 边界控件 | 删除；用官方 `collapsible="icon"` |
| 自研 token（index.css `@theme`） | 官方主题变量（`index.css` 由 Maia 预设生成） |
| `motion` 库（页面切换/列表动画） | 删除依赖；用 `tw-animate-css` + CSS 动画 |
| 品牌占位（AA 方块） | `brand-wordmark.tsx`（知守字标 + 守字标，矢量路径） |

## 5. 数据与接口

- `lib/api.ts`、`lib/apiTypes.ts`、`lib/types.ts`、全部 `hooks/*` 保持不变。
- 删除 `hooks/use-typewriter.ts`（若无引用）。
- 路由与 URL 结构（`store/app-context.tsx`）保持不变；历史面板状态改为侧栏内部实现。
- 索引自动重建：前端移除按钮；后端建议启动时做索引一致性检查（后续小改，不在本次范围）。

## 6. 测试计划

- 保留：`lib/*.test`、`hooks/use-chat/use-maintenance/use-submissions`、`store/app-context`（如仅测路由逻辑）。
- 删除：页面级测试（chat-page、confirm-sheet、maintenance-submit、tasks-page、app-shell、layout、sidebar-width）。
- 新增：`segmented-tabs` 的测量与键盘可用性（可选）。

## 7. 迁移顺序

1. 基建：依赖 + `index.css` + `components.json` + 复制官方组件（lucide 化）
2. 品牌：`brand-wordmark.tsx`
3. 外壳：app-shell / app-sidebar（含历史）
4. 对话页（含 composer / message-list / confirm-sheet / private-ref）
5. 知识库页
6. 任务页
7. 设置页（含关于）
8. 清理旧文件与依赖、测试更新、`pnpm typecheck / build / test` 通过
9. 更新 `docs/frontend-design-language.md` 为新规范

## 8. 验收标准

- `pnpm typecheck`、`pnpm build`、`pnpm test` 全绿。
- 四个页面功能与旧版一一对应（接口调用不变）。
- 28px 侧栏字标清晰；深浅色均正常。
- 无旧 token、旧自研组件残留；无 `motion` 依赖。
