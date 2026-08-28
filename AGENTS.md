## Agent skills

### Issue tracker

Issues are tracked as GitHub Issues on `andyWang1688/asset-agent`, operated via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: root `CONTEXT.md` + `docs/adr/` (created lazily by `/domain-modeling` when needed). See `docs/agents/domain.md`.

前端开发前必读 `docs/frontend-design-language.md`。

## 造与买（Build vs Buy）

- 来了新需求，优先评估是否有现成框架/组件可用；能用现成的绝不重复造轮子。
- 自己写代码只留给差异化业务逻辑：标准框架没有的、构成项目核心价值的部分。
- 本项目自留地（必须自持）：安全检测/确认闸门/脱敏、知识库编译决策、凭证隔离。
- 引入框架前先钉死边界：框架只进哪个子系统、什么永不许碰；越界即放弃引入。
- 决策依据见 `docs/adr/0004-build-vs-buy.md`，边界范例见 `docs/adr/0003-llamaindex-rag-engine.md`。
