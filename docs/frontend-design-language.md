# 前端设计语言（v2 · 2026-09 重构后）

本文是前端视觉与交互的长期约定。新增或修改页面前先读本文。旧版自定义 token 与自研组件已全部移除，请勿回退。

## 单一来源

- 主题与组件风格：shadcn/ui（Radix base）+ Maia 风格，`components.json` 的 `style` 为 `radix-maia`。
- 全局样式唯一写在 `src/index.css`：官方主题变量（`:root` / `.dark`）+ `@theme inline` 映射 + 排版/滚动条/降级规则。
- 语义颜色一律用官方 token：`bg-background`、`text-foreground`、`text-muted-foreground`、`border`、`bg-muted`、`bg-accent`、`text-destructive`、`ring`。
- 官方组件在 `src/components/ui/`，一律用 CLI 添加/更新（`npx shadcn@latest add <component>`）；禁止手写替代品。
- 共享业务组件放 `src/components/`（`segmented-tabs`、`app-shell`、`app-sidebar`、`private-ref-card`）。

## 场景色规范（没有主题色）

颜色只表达状态与注意力，不做品牌主色：

| 场景 | 约定 |
| --- | --- |
| 需要用户注意的动作（发送、确认） | 唯一允许填充的按钮；发送=黑（default），确认=绿 `bg-emerald-600 text-white hover:bg-emerald-700` |
| 常规动作（保存/测试/编辑/添加/刷新） | `outline` / `ghost`，不填充 |
| 已激活 / 已就绪 | 绿色图标 + 文字：`text-emerald-600` + `CheckCircle2` |
| 必配但未配置 | 红色警示：`text-destructive` + `CircleAlert` |
| 可选未配置 | 琥珀警示：`text-amber-600` + `CircleAlert` |
| 开关 / 单选选中 | 绿色：Switch `data-[state=checked]:bg-emerald-600`；radio `accent-emerald-600` |
| 任务状态 | 处理中=中性灰 + 慢速旋转（`animate-spin [animation-duration:3s]`），成功=绿，失败=红，待确认=琥珀 `bg-amber-500/15 text-amber-700` |
| 标签（必配/可选/版本） | `Badge variant="outline"`，不填充 |
| 危险动作 | 文字红 `text-destructive`；最终确认用 `AlertDialogAction variant="destructive"` |

## 布局

- 外壳：单侧栏（GPT 式）。`SidebarProvider > Sidebar(collapsible="icon" variant="inset") + SidebarInset`。
- `SidebarInset` 高度为 `h-[calc(100svh-1rem)]`（inset 自带上下 8px 外边距，写死 `h-svh` 会多出 16px 窗口滚动条）。
- 顶栏统一 `AppShell` 提供：`SidebarTrigger + 标题`；页面不重复画顶栏。
- 侧栏结构：品牌字标 → 新对话 → 工作区导航 → 对话历史（可折叠）→ 主题切换（页脚）。收起态隐藏历史与文字，品牌变「守」字标。
- 页面内容区：`flex w-full flex-col gap-4 px-4 py-4`，左对齐、占满宽度；不要 `mx-auto max-w-*` 居中窄栏。
- 设置页使用「分组卡片 + 行式布局」：`SettingsGroup`（官方 Card）+ `SettingsRow`（左标签/说明、右控件），见 `src/features/settings/settings-ui.tsx`。

## 品牌

- 字标组件：`src/brand-wordmark.tsx`（`Wordmark` 完整字标 / `ShouMark` 收起态）。
- 字标跟随 `currentColor`，深浅色自动反色；禁止用位图替代。
- 侧栏品牌区只放字标，不放品类说明或口号；定位文案放「设置 → 关于」。
- 文案：产品名「知守」，英文名「Memo」；定位句「本地个人资产助手……资料不出本机」。

## 动效

基调：能移动就不瞬切；只用 CSS 动画（`tw-animate-css`），不要引入 motion 库。

- 页面/标签切换：`animate-in fade-in slide-in-from-bottom-2 duration-[350ms]`。
- 新消息：`animate-in fade-in slide-in-from-bottom-1 duration-200`，不做左右滑动。
- 分段控件：`SegmentedTabs` 自带滑动胶囊（300ms 缓出）。
- 展开/收起：官方 `Collapsible`（高度动画）；任务行展开、侧栏历史折叠都走它。
- 思考态：三个跳动点（`animate-bounce` + 延迟）；流式光标用 `.streaming`。
- 必须保留全局 `prefers-reduced-motion` 降级（`index.css`），组件不得覆盖。

## 状态展示约定

- 空状态：官方 `Empty` 组件；不是错误、不用错误色。
- 加载态：与最终内容同尺寸的 `Skeleton`；短请求可用「加载中…」文本。
- Toast：`sonner`，只反馈已发生结果；表单错误仍显示在字段附近，不用 Toast 代替。
- 表单：官方 `Field`/`FieldGroup` 或设置页 `SettingsRow`；错误用 `aria-invalid` 与字段说明。

## 提交前检查

1. 是否使用了 `src/components/ui/` 的官方组件（或已有共享组件）而非手写替代？
2. 是否只使用语义 token 与场景色，没有写死颜色/间距/圆角/时长？
3. 是否覆盖空状态、加载态、错误展示与 reduced-motion？
4. 运行 `pnpm typecheck`、`pnpm lint`、`pnpm test`。
