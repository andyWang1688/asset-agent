# 开源敏感文件脱敏复核 UI：可复用候选

核验日期：2026-09-17。只读官方仓库、代码与官方指南；未安装运行，未上传任何用户文件。结论中的功能属于文档/源码确认，不是运行验收。

## 结论

- **最接近“自动识别 → 人工复核 → 导出”的完整开源应用：`seanpedrick-case/doc_redaction`。** PDF/图片的复核交互可以直接参考，甚至作为独立本地工具评估；AGPL 许可不适合未经评估直接搬进闭源产品。
- **PDF 手工编辑器参考：`Stirling-Tools/Stirling-PDF`。** 已有选中文字、画区域、移除待处理标记、集中 Apply 的完整 UI；不是已证实的“中文 PII 自动识别 + Office 原格式复核”方案。
- **Presidio 是检测/匿名化引擎；官方 Streamlit 是文本演示，不是完整文件审核台。** 可以复用底层能力，不能拿 Demo 代替审核产品。
- 没有在本次证据中找到一个同时覆盖 PDF、复杂 Excel、Word 原版式、逐处接受/拒绝且可无缝嵌入现有 React 产品的成品。

## 1. doc_redaction：完整 Gradio 应用，PDF 审核最匹配

仓库：[seanpedrick-case/doc_redaction](https://github.com/seanpedrick-case/doc_redaction)。本次代码基准：[`33165c5eaee43056ba9444214fbc47dea6d3c4c4`](https://github.com/seanpedrick-case/doc_redaction/tree/33165c5eaee43056ba9444214fbc47dea6d3c4c4)。

### 已确认交互

官方 [User Guide：Review suggested redactions](https://seanpedrick-case.github.io/doc_redaction/src/user_guide.html#document-viewer) 明确展示文档页 + 检测框 + 实体标签；可移动/缩放框，修改标签/颜色，双击 Remove 或按 Delete 删除，也可以手动画框。

官方指南原文：

> “Double click on a box to enter the menu to change label, colour, or remove the box.”

同一指南的复核表支持：

- `Exclude specific redaction row`：排除单项。
- `Exclude all redactions with the same text as selected row`：同文批量排除。
- `Exclude all redactions in table`：对过滤后的表批量排除。
- 搜索原始提取文本后补充脱敏，撤销最近新增/移除；`Apply redactions to PDF` 应用结果。
- 官方明确要求人工审阅全部输出，不能把检测结果当作准确性保证。

### 文件范围与不能夸大的地方

| 文件 | 已确认 | 边界 |
|---|---|---|
| PDF、PNG、JPG | 自动识别；页面框选复核；导出 PDF 等结果 | OCR、实体识别准确率和中文能力未实测；最终 PDF 不可恢复性未实测 |
| DOCX | 输入，段落/表格文本匿名化，输出 `_redacted.docx` 和 CSV 日志 | 不是证实的 Word 原版式逐项审核；代码清空段落 runs 后加一个新 run，表格单元格直接改 `.text`，局部富文本格式不能保证 |
| XLSX、CSV（README 还列 Parquet） | 选 sheet/列，检测并替换文本；源码确认 XLSX 输出 | 官方要求每张表从 A1 开始、只有一个简单表且无其他信息；不是复杂报表保真工具；源码经 DataFrame 重写 sheet，公式/图表/格式不能承诺保留 |

证据：

- [官方 Word/Excel 指南](https://seanpedrick-case.github.io/doc_redaction/src/user_guide.html#word-or-tabular-data-files-xlsxcsv)：原文 “a single table starting from the first cell (A1), and no other information in the sheet”。
- [DOCX 处理源码 L633–744](https://github.com/seanpedrick-case/doc_redaction/blob/33165c5eaee43056ba9444214fbc47dea6d3c4c4/tools/data_anonymise.py#L633-L744)：`element.clear()`、`element.add_run(new_text)`、`element.text = new_text`、`doc.save(output_docx_path)`。
- [XLSX 输出源码 L1457–1476](https://github.com/seanpedrick-case/doc_redaction/blob/33165c5eaee43056ba9444214fbc47dea6d3c4c4/tools/data_anonymise.py#L1457-L1476)：`if_sheet_exists="replace"`，`anon_df_out.to_excel(...)`。指南只讲 CSV 输出，但当前源码也确认 XLSX/DOCX 输出；两者不可混为“只导出 CSV”。

### 许可、本地运行和依赖重量

- [pyproject.toml](https://github.com/seanpedrick-case/doc_redaction/blob/33165c5eaee43056ba9444214fbc47dea6d3c4c4/pyproject.toml) 明确 `AGPL-3.0-only`，注释说明与 PyMuPDF 使用有关；[LICENSE](https://github.com/seanpedrick-case/doc_redaction/blob/33165c5eaee43056ba9444214fbc47dea6d3c4c4/LICENSE) 为 AGPL v3。复用/部署的开源义务应单独评估，不能当作 MIT 组件。
- [README 本地安装](https://github.com/seanpedrick-case/doc_redaction/blob/33165c5eaee43056ba9444214fbc47dea6d3c4c4/README.md)：虚拟环境内 `pip install -e .` 后 `python app.py`；支持 Docker，也支持 PyPI 安装后 `python -m app`。
- Python >=3.10、Gradio、Presidio、spaCy、PyMuPDF、pikepdf、pandas/openpyxl/python-docx 等，系统依赖 Tesseract + Poppler；这是一套应用，不是轻量前端组件。Paddle/Torch/Transformers/VLM 是额外依赖，不应为了基础复核默认装全套。
- README 的约 40 GB 磁盘/24 GB VRAM 说明针对 llama.cpp/vLLM 大模型组合部署，**不是基础本地应用门槛**。
- 可配置本地 OCR/PII；也有 AWS、Gemini/OpenAI 等能力，使用前必须锁定本地配置。此处未确认默认配置的所有出站行为。

**适合借鉴/复用：** 文档坐标框与 Findings 列表联动、单项/同文批量排除、人工补漏、复核结果再应用。它本身已使用 Presidio，不必把二者当作竞争替代品。

## 2. Stirling-PDF：完整 PDF 平台，手工审核能力可参考

仓库：[Stirling-Tools/Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF)。本次代码基准：[`40748502e2870ce9b4c5aff6f0f7545a6a2be1c7`](https://github.com/Stirling-Tools/Stirling-PDF/tree/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7)。

### 已确认交互与范围

- [`ManualRedactionControls.tsx` L137–180](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/frontend/editor/src/core/components/tools/redact/ManualRedactionControls.tsx#L137-L180) 明确：`Select text or draw areas on the PDF to mark content for redaction.`，显示 pending 数量，`Apply Redactions` 后保存。
- [`RedactionSelectionMenu.tsx` L61–62、L134–149](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/frontend/editor/src/core/components/viewer/RedactionSelectionMenu.tsx#L134-L149) 有 `removePending` 和 `Remove this mark`；应用前警告永久删除、不可撤销。由此可确认“待确认标记”与“最终应用”是两个阶段，而不是一画框就直接破坏原文。
- [`RedactModeSelector.tsx`](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/frontend/editor/src/core/components/tools/redact/RedactModeSelector.tsx) 区分 Automatic / Manual；[`WordsToRedactInput.tsx`](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/frontend/editor/src/core/components/tools/redact/WordsToRedactInput.tsx) 允许添加/移除匹配词。**不能仅因叫 Automatic 就声称有成熟 PII 语义识别复核。**
- 已确认的是 PDF 工具；平台虽有 Office → PDF 转换，不等于 XLSX/DOCX 原格式逐项审核与回写。

### 许可、本地运行与复用成本

- [README](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/README.md) 自称 open-core；[LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/LICENSE) 是 MIT 加目录排除：`app/proprietary`、`app/saas`、`engine`、前端 proprietary/desktop/saas/cloud 等适用各自许可。上述 `frontend/editor/src/core/...` 与 `app/core/...` 不在排除目录内，按顶层声明属于 MIT；依赖仍需独立核对。**不是整仓纯 MIT。**
- 官方 Docker 运行方式为 `docker run -p 8080:8080 docker.stirlingpdf.com/stirlingtools/stirling-pdf`；评估时可将绑定改为 `127.0.0.1:8080:8080` 限本机访问。未实际执行安装。
- [DeveloperGuide](https://github.com/Stirling-Tools/Stirling-PDF/blob/40748502e2870ce9b4c5aff6f0f7545a6a2be1c7/DeveloperGuide.md)：Spring Boot/JDK 25 + React/TypeScript/Vite/Mantine，PDFBox，转换/OCR 可选 LibreOffice/Tesseract/qpdf；桌面另有 Tauri/Rust。整套部署比嵌入一个 UI 组件重。
- 其复核组件依赖 ViewerContext、RedactionContext、导航、文件管理等上下文；不应描述成可直接复制即用的无依赖 React 组件。

**适合借鉴/复用：** PDF 文本/矩形标注、待应用计数、移除标记、不可逆 Apply 的交互；已有 MIT core 值得做依赖/许可边界评估，但不是替换整个敏感内容闸门。

## 3. Presidio：底层引擎，不把官方 Demo 当完整审核产品

原 `microsoft/presidio` 本次 GitHub API 已重定向至 [data-privacy-stack/presidio](https://github.com/data-privacy-stack/presidio)，仓库 MIT。

- 官方 [Streamlit index](https://github.com/data-privacy-stack/presidio/blob/main/docs/samples/python/streamlit/index.md) 的标题是 `Simple demo website for Presidio`，原文 “Here's a simple app ... to create a demo website”。
- [Demo 源码](https://github.com/data-privacy-stack/presidio/blob/main/docs/samples/python/streamlit/presidio_streamlit.py)：文本 Input/Output、实体类型多选、阈值、allow/deny lists；本次未找到 PDF/Office 上传、坐标审核、逐命中接受/拒绝的完整流程证据。
- 本地可虚拟环境安装 `requirements.txt` 后 `streamlit run presidio_streamlit.py`；官方提示 demo 安装 transformers/flair 等 **引擎本身并非必须** 的依赖。

## 安全与验收边界

这些工具可以省掉通用的展示/标记工作，但不能外包本项目的安全闸门、凭证隔离和明文外发决策。当前仅确认产品/代码能力；中文识别召回率、隐藏 sheet/批注/页眉页脚、PDF 隐藏文本清除、日志中的原文、取消操作不泄露、全部离线运行均未验收。尤其 doc_redaction 的日志明确包含 underlying text，不能把审核日志误当成已脱敏内容转发。
