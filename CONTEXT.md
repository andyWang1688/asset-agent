# AssetAgent

本地优先的个人资产知识 Agent：收集资产资料，逐项人工裁决敏感发现，脱敏后编译成 Markdown Wiki，并基于 Wiki 问答。

## 定位

**用户（User）**：运行自己那份本地 AssetAgent 实例的人。每个用户 = 一次完全独立的单用户部署，互不共享数据。
_Avoid_：客户、租户

## 管道

**Source（来源）**：通过确认闸门后入库的一份资料。落盘为脱敏 Raw 副本并在 `sources` 表记一行。
_Avoid_：document、文件

**Raw**：Source 的脱敏落盘副本（`workspace/raw/inbox/`）。秘密只以引用存在，原文永不持久化。
_Avoid_：original（原文不落盘）

**Finding**：检测管线对输入文本的一条发现：span、类别（credential / pii / unknown_suspect）、置信度、建议动作。
_Avoid_：alert、命中

**Submission（待确认提交）**：含 Finding 的输入，以 AES-GCM 密文暂存等待裁决。确认前不落盘、不调模型。

**Decision（裁决）**：对单个 Finding 的用户选择：store（存 Vaultwarden 并脱敏）/ redact（仅脱敏）/ allow（误报放行）。
_Avoid_：审批

**Gate（确认闸门）**：一份 Submission 的全部 Finding 必须拿到 Decision 才允许文本继续流动的关卡。

## 脱敏

**SECRET_REF**：占位符 `[SECRET_REF:name]`，替换已入库凭证；值只存在于 Vaultwarden。

**REDACTED**：占位符 `[REDACTED:rule]`，替换 PII 或疑似文本；原值销毁。

## 模型角色

**knowledge model（知识库模型）**：唯一激活的编译/问答模型。必配；缺失时提交与问答 fail-closed。

**security model（安全增强模型）**：可选的本地端点检测模型，只能新增或加严 Finding；禁止公网。

## 知识

**Wiki**：`workspace/wiki/` 下的 Markdown 页面，知识的事实源；可人工编辑、Git 版本化。

**编译（Compile）**：Worker 把脱敏 Source 经 LLM 转为 Wiki 页面创建/更新的过程。

**Index（索引）**：Wiki 页面的派生索引（文件级 JSON + 本地向量），可删除并从 Markdown 重建。
_Avoid_：database（它不是事实源）

## 问答

**对话记忆（Memory）**：当前提问携带的历史上下文。窗口/压缩/摘要交给 LlamaIndex 记忆组件；存储唯一事实源是 `chat_log`，每次请求从库中水合，不由框架持久化。
_Avoid_：会话状态、上下文缓存

## 安全策略（用户视角术语）

**默认模式**：安全两档之一。扫描后按既定默认动作自动处理（凭证存 Vaultwarden 并脱敏、PII 脱敏），无人工步骤。
_Avoid_：便捷档、自动档

**确认模式**：安全两档之一。每份资料入库前经确认页人工过目；无命中也过一眼。
_Avoid_：严格档、手动档

**确认页三动作**：同意（按建议一键处理）/ 拒绝（整份丢弃）/ 按我说的做（逐项裁决+预览编辑）。

**模式匹配 / 关键词联想 / 乱串检测**：三个检测层的用户视角名称，分别对应正则层、上下文层、熵层。技术名只出现在高级折叠。
