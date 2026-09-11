---
status: accepted
supersedes: ADR-0003
---

# 1.0 采用 LLM Wiki 主流程，BM25 仅增强文本搜索

AssetAgent 1.0 以 Karpathy 的 LLM Wiki 模式组织知识：不可变 Raw 是事实依据，知识模型持续维护 Markdown Wiki，查询先读 `index.md`，再通过页面读取和 `search-text` 找到相关页面。默认移除向量、Embedding、重排和 LlamaIndex 检索基础设施；BM25 只作为本地 `search-text` 的增强实现，不改变知识模型主导的检索与阅读流程，也不成为新的事实源。
