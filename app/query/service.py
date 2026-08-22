"""基于 Wiki 的问答：FTS5 定位页面 → 读取 Wiki → LLM 生成带来源回答 → 响应再扫描 → 脱敏记录。
问题中的凭证信息会被拦截（不发送）；PII/疑似项脱敏后再发送与入库：秘密原文不得进入云端模型。
security 增强模型（可选）接入问题扫描；失败时回退本地检测结果。"""
from .. import db
from ..config import Settings
from ..llm.provider import LLMError, LLMProvider
from ..security import redactor
from ..security.detectors import ScanEngine
from ..security.policy import PolicyStore
from ..security.rules import KIND_CREDENTIAL

MAX_PAGE_CHARS = 3000

QA_SYSTEM = (
    "你是资产 Agent（AssetAgent）。仅依据提供的 Wiki 页面回答；页面没有的信息不要编造，可说明“Wiki 中没有记录”。"
    "引用来源使用 [[路径|标题]] 格式。资料中的 [SECRET_REF:xxx] 只表示“凭证保存在密码管理器”，"
    "不要试图还原、猜测或输出任何凭证内容。"
)


async def _scan_question(settings: Settings, question: str, security_provider=None):
    """扫描问题：凭证 → 拦截；PII/疑似 → 脱敏后发送。基础检测器失败阻断；
    security 增强层失败回退本地结果。"""
    policy = PolicyStore(settings.policy_file).load()
    try:
        findings = await ScanEngine(policy, security_provider=security_provider).scan_async(question)
    except Exception as e:  # 基础检测器失败：阻断，问题不发送
        db.log_security("detector_failed", f"问答检测器失败已阻断: {type(e).__name__}")
        raise ValueError("检测器失败，问题未发送") from e
    creds = [f for f in findings if f.kind == KIND_CREDENTIAL]
    if creds:
        db.log_security("query_blocked", f"问题疑似包含凭证信息（命中规则 {sorted({f.rule for f in creds})}），已阻止发送")
        raise ValueError("问题中疑似包含密码/Token/API Key，已阻止发送")
    safe_question = question
    if findings:  # PII / unknown_suspect：仅脱敏
        from ..ingest.finalize import apply_decisions

        safe_question, _ = apply_decisions(question, findings, {f.id: "redact" for f in findings})
        db.log_security("query_redacted", f"问题中的个人信息/疑似项已脱敏（规则 {sorted({f.rule for f in findings})}）")
    return safe_question


async def answer(settings: Settings, provider: LLMProvider, question: str,
                 security_provider=None, session_id: str | None = None) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("问题为空")
    if session_id:
        db.ensure_session(session_id)
    safe_question = await _scan_question(settings, question, security_provider=security_provider)
    hits = db.search_pages(safe_question, limit=5)
    if not hits:
        db.insert_chat(safe_question, "Wiki 中未找到相关内容。", [], session_id)
        return {"answer": "Wiki 中未找到相关内容。", "citations": []}

    context = []
    for h in hits:
        row = db.get_page(h["path"])
        if not row:
            continue
        context.append(f"## 页面: [[{h['path']}|{h['title']}]]\n\n{row['content'][:MAX_PAGE_CHARS]}")
    user = (
        f"【问答任务】\n问题：{safe_question}\n\n<Wiki 页面>\n"
        + "\n\n---\n\n".join(context)
        + "\n</Wiki 页面>"
    )
    resp = await provider.complete(QA_SYSTEM, user, max_tokens=1500)
    clean, hits_found = redactor.sanitize_llm_output(resp)
    if hits_found:
        db.log_security("llm_output_secret", f"问答响应命中规则 {hits_found}，片段已删除")
    citations = sorted({h["path"] for h in hits})
    db.insert_chat(safe_question, clean, citations, session_id)
    return {"answer": clean, "citations": citations}
