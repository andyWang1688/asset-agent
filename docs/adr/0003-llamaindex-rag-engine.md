# 问答与检索引擎采用 LlamaIndex（Python）

业务收敛为两件事：RAG 检索回答 + 根据输入自动更新知识库。LlamaIndex 是 Python 生态的 RAG 专精框架（混合召回、重排、带引用的查询引擎、多轮记忆、RAG 评测），与业务逐条命中；对比项：pi agent core 是 TS 的 agent 运行时（无检索能力、语言不符），OpenAI Agents SDK/pydantic-ai 不提供检索件，LangChain 生态过重。

**边界铁律（越界即放弃引入）**：
- LlamaIndex 只进入问答子系统与索引构建；安全管线、编译决策管道、凭证隔离零改动。
- Markdown Wiki 永远是事实源；LlamaIndex 索引与 FTS5 同为派生索引，可删除、可从 Markdown 重建。
- 编译管道"决定怎么维护知识"的逻辑自持，框架只负责"把维护好的知识变得可检索"。
- embedding 优先本地模型（Ollama/sentence-transformers，BGE 系），建索引内容不出本机；仅生成回答走已配置的云端知识库模型（内容已脱敏）。
- 问答引擎位于既定四条缝之内：检索可插拔（Retriever）、上下文组装单点化、引擎可替换、安全扫描钉在出入口。
