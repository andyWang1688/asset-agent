# 敏感信息审核交互：商业产品参考

日期：2026-09-17。证据为官方帮助/功能页面，不是登录后的实机验收。没有上传用户文件，也没有采信厂商零漏检或效率倍数等营销保证。

## Redactable

来源：https://www.redactable.com/features/redaction-wizard

官方列出四种入口：Auto、Categories、Search Text、Manual。
- Auto 自动标出姓名、证件、联系方式等；应用之前由用户 review and approve。
- Categories 可选全部或部分类别，按类别批量处理；支持保存类别模板。
- Search Text 搜索词语、短语或导入词列表，显示全文件出现位置。
- Manual 在文件中选择文字或拖出区域，可以处理大块区域/整页。
- 工作流：Open Document → Choose Method → Identify Content → Preview → Finalize。
- 预览可修改，最终应用后永久删除目标内容；报告/证书作为结果审计材料。
- 这是商业在线产品，不是本项目可以直接嵌入的开源 UI；不能将本地敏感资料发给它，仅用公开材料作交互参考。

## Adobe Acrobat Pro

来源：https://helpx.adobe.com/acrobat/using/removing-sensitive-content-pdfs.html

官方人工操作：Redact text and images → 在文字或图片上拖选 → Apply → 选择是否 sanitize 隐藏内容 → Continue → 另存文件。

搜索批量操作来源：https://helpx.adobe.com/acrobat/desktop/protect-documents/redact-pdfs/redact-text.html

搜索支持单词/短语、多个词或模式；Check All 选择全部命中，也可逐项勾选，先 Mark Checked Results，再 Apply。

这里的核心参照是文档内标记与最终应用分离，而非让用户编辑一份程序生成的安全报告。商业桌面 PDF 工具，不是通用 Word/Excel 本地 Agent 方案。

## 对 AssetAgent 的设计推论

- 最接近的产品类目是 document redaction review，而不是密码库导入。此前密码管理器导入类比只适合批量导入，不足以说明漏检复核。
- 审核对象应是资料本身：原文/处理结果切换、命中高亮、手工补标、批量处理同一值或类型；报告保留为后台执行与审计数据。
- 用户可以检查未标记内容，不能只过滤展示已命中的项目。低置信提示只作导航，不承诺其他内容安全。
- 本地人工原文预览如果加入，必须明确是本次提交的受控预览，不应扩大为 Private Raw 通用读取接口；云端知识模型仍只获得被允许发送的最终脱敏内容。
- PDF 页内标记不直接解决复杂 Excel 表头/多块表格识别。要做到“点击单元格补标”，需要保留工作表/行列与文本 span 映射；换 UI 或引入 PII 引擎均不能自动补足映射。
- 尚未实施 UI 重构或引入任何第三方服务。
