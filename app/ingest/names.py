"""手动资料的短文件名：只接收脱敏文本，不调用模型。"""
import re


def text_source_name(preview: str) -> str:
    # 引用标识与替换标记不是摘要，不带进文件名。
    text = re.sub(r'\[🔒 [^\]]+\]\(private:[^)]+\)|\[REDACTED:[^\]]+\]|\[SECRET_REF:[^\]]+\]', '', preview)
    text = re.sub(r'(?m)^[^\n=:：]{1,24}[=:：]\s*$', '', text)
    first = next((s.strip() for s in re.split(r'[\n。！？!?；;]', text) if s.strip()), '')
    first = re.sub(r'[<>:"/\\|?*\x00-\x1f#`\[\]]', '', first)
    title = re.sub(r'\s+', ' ', first).strip(' .')[:20].rstrip(' .')
    return (title or '对话') + '.txt'
