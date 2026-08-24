"""基于 Wiki 的问答：混合检索定位页面 → 读取 Wiki → LLM 生成带来源回答 → 响应再扫描 → 脱敏记录。
问题中的凭证信息会被拦截（不发送）；PII/疑似项脱敏后再发送与入库：秘密原文不得进入云端模型。
security 增强模型（可选）接入问题扫描；失败时回退本地检测结果。"""
from .. import db
from ..config import Settings
from ..llm.provider import LLMError, LLMProvider
from ..security import redactor
from ..security.detectors import ScanEngine
from ..security.policy import PolicyStore
from ..security.rules import KIND_CREDENTIAL
from .engine import QuestionAnswerEngine
from .hybrid import HybridQuestionAnswerEngine


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
                 security_provider=None, session_id: str | None = None,
                 engine: QuestionAnswerEngine | None = None) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("问题为空")
    if session_id:
        db.ensure_session(session_id)
    safe_question = await _scan_question(settings, question, security_provider=security_provider)
    # 对话记忆：每次请求从 chat_log 水合最近 N 轮问答（唯一持久化事实源），
    # 窗口裁剪只取最近 chat_memory_rounds 轮，记忆组件自身不做任何持久化。
    history = []
    if session_id and settings.chat_memory_rounds > 0:
        history = db.list_chat_history(session_id, settings.chat_memory_rounds)
    # 未显式传入引擎时装配默认的单一混合引擎（LlamaIndex：BM25+向量+重排）。
    engine = engine or HybridQuestionAnswerEngine(settings)
    result = await engine.answer(provider, safe_question, history=history)
    clean, hits_found = redactor.sanitize_llm_output(result["answer"])
    if hits_found:
        db.log_security("llm_output_secret", f"问答响应命中规则 {hits_found}，片段已删除")
    citations = result["citations"]
    db.insert_chat(safe_question, clean, citations, session_id)
    return {"answer": clean, "citations": citations}
