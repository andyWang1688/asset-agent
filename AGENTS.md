# AGENTS.md

## Agent 技能

### Issue 跟踪

Issue 统一记在 `andyWang1688/asset-agent` 的 GitHub Issues，用 `gh` CLI 操作。见 `docs/agents/issue-tracker.md`。

### 分诊标签

默认五标签（`needs-triage` 待分诊 / `needs-info` 需补充信息 / `ready-for-agent` 可交给 agent / `ready-for-human` 需人处理 / `wontfix` 不修）。见 `docs/agents/triage-labels.md`。

### 领域文档

单上下文布局：根目录 `CONTEXT.md` + `docs/adr/`（按需由 `/domain-modeling` 创建）。见 `docs/agents/domain.md`。

## 前端开发原则

- 动前端前必读 `docs/frontend-design-language.md`（设计语言与动效规范）。
- 写组件前先查 `frontend/src/components/ui/` 有没有现成实现，shadcn 官方组件优先；有现成的绝不手写替代。
  历史教训：sidebar、card 曾被手写替代，后已换回官方组件。

## 造与买（Build vs Buy）

- 来了新需求，优先评估是否有现成框架/组件可用；能用现成的绝不重复造轮子。
- 自己写代码只留给差异化业务逻辑：标准框架没有的、构成项目核心价值的部分。
- 本项目自留地（必须自持）：安全检测/确认闸门/脱敏、知识库编译决策、凭证隔离。
- 引入框架前先钉死边界：框架只进哪个子系统、什么永不许碰；越界即放弃引入。
- 决策依据见 `docs/adr/0004-build-vs-buy.md`，边界范例见 `docs/adr/0003-llamaindex-rag-engine.md`。
