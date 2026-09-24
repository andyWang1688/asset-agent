# 发布审查六项修复验收

范围：基于已发布的 v1.0.0（`f0b7db6`），验证本轮六项修复。后端提交 `c226f3e`，前端提交 `c6e7566`；不改写 v1.0.0 的历史验收结果。

## 功能回归

| 输入 / 操作 | 预期及禁止 | 证据 |
| --- | --- | --- |
| 先讨论“青松计划”，再新增匹配它的敏感规则，继续提问 | 历史问答按当前策略脱敏；禁止旧历史原值进入模型 | `test_history_rescanned_after_security_policy_change` |
| 保存凭证后删除对应保险柜条目，再提交同值资料 | 重建已删除条目；下一轮复用新条目，禁止引用已删除 ID 或持续重复创建 | `test_deleted_vault_item_is_recreated`，覆盖相同与不同来源 |
| 同一文字完成维护后再次提交 | 新报告、新任务，复用来源与凭证；同一提交并发确认仍只执行一次 | `test_repeated_manual_input_creates_new_round`、`test_concurrent_confirm_creates_credential_once` |
| 文件先单独上传，再加入其他附件或改变顺序 | 同一审查结果复用 Source、Raw、原件；私密引用不随批次位置改变 | `test_source_identity_is_independent_of_batch` |
| 等待问答时继续输入，或切到新会话输入 | 保留新草稿，忽略旧请求；新会话输入相同文字也不能被清空 | `frontend/src/features/chat/chat-page.test.tsx` |
| 快速选择 Wiki A、B，调整响应顺序和失败结果 | 目录、正文、错误和加载状态都属于最后一次选择 | `frontend/src/hooks/use-wiki.test.tsx` |

本地后端 `.venv/bin/python -m pytest -q`：**488 passed**。前端 `vitest run`：**92 passed / 16 files**。`tsc --noEmit`、ESLint、Vite build、`uv lock --check`、`git diff --check` 通过；ESLint 保留 5 条既有警告，侧栏测试仍有既有嵌套 `li` 警告。

## Docker 与浏览器

实际构建当前源码的 Linux ARM64 镜像，未替换正式运行容器：

- 后端：`asset-agent-backend:release-review-20260924`，镜像 ID `e9f39eacda2b9c8bb2dd46be3778e920a49e79ea6c0143288e3ef6011b33c900`。
- 前端：`asset-agent-frontend:release-review-20260924`，镜像 ID `1fdf3c00ee433103b2beea729b566fade48e6e95f258d5b577f433097a049c0f`。
- 浏览器通过独立网络与 `127.0.0.1:8011` 访问正式 Nginx/Vite 构建产物和真实 FastAPI/Worker；运行数据为容器内独立目录，模型与保险柜是合成替身。

实际页面验收：

1. 问答处理中切换新会话，输入新草稿；旧问答完成后草稿保持不变。
2. 上传两个合成 TXT，切换审查文件，确认右栏显示私密引用；一次确认后进入任务页，最终显示成功并更新 1 页。数据库只读核对：该任务关联 2 个 Source，归档 2 份原件。
3. Wiki A 人为延迟 2 秒，先点 A 再点 B；待 A 请求完成，正文仍为 B，未被过期响应覆盖。

夹具初次启动时先缓存默认策略、后用另一个 PolicyStore 写确认策略，导致预备任务 #1 按“安全策略已变化”失败；改用产品设置 API 同步当前策略后，正式验收任务 #2 成功。该失败不是成功用例，未删除或掩盖记录。

## 发布边界

- 本文不证明真实外部模型兼容性、真实 Vaultwarden 故障恢复或旧开发数据无损迁移；本轮没有调用用户模型、写入真实保险柜或重启正式服务。
- 本次代码需要通过所在 PR 的最终提交 CI 后合并；远端结果以 GitHub Actions 检查为准，不用旧 v1.0.0 的绿灯替代。
- v1.0.0 已发布。本次修复纳入 v1.0.1；实际发布状态以 GitHub Release 为准。
