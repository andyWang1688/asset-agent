# 前端设计语言

这份文档是前端视觉与交互的长期约定。新增或修改页面前先读本文；页面层只组合共享组件并引用 token，不新增局部颜色、间距、圆角、字号或动效数值。

## 单一来源

- token 唯一写在 `frontend/src/index.css` 的 `@theme` 中，同时被 Tailwind 生成工具类和 CSS `var(...)` 使用。
- 优先使用语义 token（例如 `bg-bg`、`text-muted`、`rounded-md`、`p-content`、`duration-fast`），不要写任意值或复制颜色值。
- 共享组件放在 `frontend/src/components/layout/`；页面只负责业务状态与内容编排。

## 颜色

| 用途 | token | 约定 |
| --- | --- | --- |
| 页面背景 | `--color-bg` | 页面最底层背景 |
| 卡片/输入框表面 | `--color-surface` | 与背景区分的内容表面 |
| 主文字 | `--color-fg` | 标题、正文、主要操作 |
| 次要文字 | `--color-muted` | 说明、时间、辅助信息 |
| 普通边框 | `--color-border` | 统一 1px 分隔线 |
| 强边框 | `--color-border-strong` | 输入框或需要强调的边界 |
| 柔和填充 | `--color-soft` | hover、选中背景、禁用底色 |
| 品牌强调 | `--color-accent` / `--color-accent-soft` | 焦点、进度、积极状态 |
| 成功 | `--color-ok` / `--color-ok-soft` | 完成、可用、通过 |
| 提示 | `--color-info` / `--color-info-soft` | 非阻断提示 |
| 警告 | `--color-warn` / `--color-warn-soft` | 需要留意但可继续 |
| 错误 | `--color-danger` / `--color-danger-soft` | 校验失败、阻断性错误 |

颜色只表达状态，不用颜色代替文字或图标；文字与背景保持可读对比度。

## 间距

间距按 4px 基准，优先使用以下语义档位：

| token | 值 | 典型用途 |
| --- | --- | --- |
| `--spacing-compact` | 8px | 图标与文字、紧凑控件 |
| `--spacing-control` | 12px | 控件内边距、字段间距 |
| `--spacing-content` | 16px | 卡片内边距、内容组间距 |
| `--spacing-section` | 24px | 页面区块间距 |
| `--spacing-section-lg` | 28px | 大区块或标题下方 |
| `--spacing-page` | 24px | 桌面页面边距 |
| `--spacing-page-mobile` | 16px | 窄屏页面边距 |
| `--spacing-page-narrow` | 14px | 极窄屏页面边距 |
| `--spacing-overlay` | 32px | 弹窗、抽屉的宽松内边距 |

需要新增档位时先复用最接近的 token；不要在页面 class 中写 `px-[...]`、`gap-[...]` 等任意值。

## 圆角、阴影与字号

- 圆角：`xs`（5px）用于徽标和代码片段，`sm`（7px）用于小控件，`md`（10px）用于按钮/输入，`lg`（14px）用于卡片，`xl`（16px）用于大型容器，`pill` 用于胶囊标签。
- 阴影：`shadow-panel` 用于普通卡片，`shadow-pop` 用于浮层；不要按页面单独调阴影。
- 字体：正文使用 `font-sans`，技术内容使用 `font-mono`。字号 token 为 `text-meta`（10px）、`text-caption`（12px）、`text-panel`/`text-label`（13px）、`text-body`（14px）、`text-input`（15px）、`text-heading`（16px）、`text-title`（18px）、`text-display`（响应式 28–40px）。
- 行高使用 `leading-tight`（1.25）、`leading-body`（1.6）和 `leading-relaxed`（1.75）。

## 动效

动效基调是“能移动就不瞬切”：

- `duration-fast` / `--motion-duration-fast`：150ms，按钮 hover、按压、焦点等微交互。
- `duration-standard` / `--motion-duration-standard`：300ms，分段开关、菜单高亮和普通状态切换。
- `duration-slow` / `--motion-duration-slow`：450ms，页面级进入/退出和抽屉等大范围变化。
- 位移类使用 `ease-spring` / `--motion-ease-spring`（轻微回弹）；淡入淡出类使用 `ease-fade` / `--motion-ease-fade`，其值固定为 `cubic-bezier(0.32, 0.72, 0, 1)`。
- 使用 Motion 时，位移类交给 spring transition；CSS 过渡使用对应时长和曲线 token，不在组件中写死数值。
- 必须尊重 `prefers-reduced-motion: reduce`：所有动画和过渡降级为无动画，滚动行为改为 auto。全局降级规则已在 `index.css`，组件不得覆盖它。

## 状态展示约定

### 空状态

空状态不是错误：使用简短标题、解释当前为空的原因和一个可选主操作；保持容器尺寸稳定，避免页面跳动。无数据时不要显示错误色。

### 加载态

优先使用与最终内容同尺寸的 skeleton，保留标题、列表和卡片的布局；短请求可用简短“加载中…”文本，禁止用无限旋转遮挡整个页面。加载期间禁用会重复提交的操作。

### Toast

Toast 只反馈已发生的结果，文案一句话说明“发生了什么”；成功/提示/警告/错误分别使用对应语义色。成功和提示自动消失，错误保留更久并提供可读的修复信息；不可把 Toast 当作表单错误或唯一的无障碍反馈。

### 表单错误

错误显示在对应字段附近，使用 `--color-danger`、清晰文案和 `aria-describedby` 关联；字段错误出现时不改变整体布局结构。提交失败且无法归属单个字段时，在表单顶部显示摘要，并保留字段级错误。

## 提交前检查

1. 页面是否只使用共享组件和 `index.css` token？
2. 是否存在写死的颜色、间距、圆角、字号、时长或曲线？
3. 是否覆盖空状态、加载态、Toast、表单错误和减少动态效果？
4. 运行 `pnpm typecheck` 与现有测试。
