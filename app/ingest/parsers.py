"""文档解析：Markdown / TXT / PDF（首版只支持可提取文本的 PDF，不做 OCR）。"""
import io

from pypdf import PdfReader


def parse_upload(filename: str, data: bytes, max_mb: int) -> tuple[str, str]:
    lower = (filename or "").lower()
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"文件超过 {max_mb}MB 限制")
    if lower.endswith((".md", ".txt", ".text")):
        return "text", data.decode("utf-8", errors="replace")
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t)
        text = "\n\n".join(parts).strip()
        if not text:
            raise ValueError("PDF 无可提取文本（扫描件暂不支持 OCR）")
        return "pdf", text
    raise ValueError("仅支持 Markdown / TXT / PDF")
