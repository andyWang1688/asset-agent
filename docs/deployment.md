# 部署级安全配置

安全策略页面只负责常用的结构化开关；以下配置保留在部署环境的 `config/policy.yaml`（默认路径为 `data/config/policy.yaml`），不通过前端 YAML 编辑器修改。

```yaml
actions:
  defaults:
    credential: store
    pii: redact
    unknown_suspect: redact
detection:
  extra_max_input_chars: 200000
  extra_exec_timeout_seconds: 2.0
  context:
    window: 40
    boost: 0.15
  entropy:
    max_findings: 50
```

- `actions.defaults`：默认模式下各类发现的处置动作；凭证存入 Vaultwarden 后脱敏，PII 仅脱敏。
- `detection.extra_max_input_chars` / `extra_exec_timeout_seconds`：自定义规则输入长度与执行超时护栏。
- `detection.context.window` / `boost`：关联窗口与命中加成。
- `detection.entropy.max_findings`：单份资料的乱串发现上报上限。

熵值灵敏度预设（页面只显示档位名称）：敏感 `3.2/12/10`、平衡（默认）`3.5/16/12`、保守 `4.0/20/16`，依次对应 `min_shannon/min_length/context_min_length`。

修改后由服务启动时加载并执行现有策略校验；非法配置保留上一份有效策略。请通过部署配置管理与回滚流程变更这些键。
