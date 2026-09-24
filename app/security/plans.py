"""待确认报告的只读 Wiki 计划：安全预览 → 固定快照 → 一次确认。

审查确认即创建任务；生成计划、保存资料、执行维护是同一任务的后台阶段。
模型只获得重新扫描后的资料；
内部计划快照不可由客户端提交或更改。"""
import asyncio
import hashlib
import json
import traceback
import uuid

from .. import crypto, db
from ..ingest import transaction
from ..ingest.finalize import GateBlockedError, locate_allow_spans, rescan_guard, validate_decisions
from ..wiki import compiler
from ..wiki.tools import ToolBudgetExceeded
from . import entries, redactor
from .detectors import ScanEngine

_locks: dict = {}


def operation_lock():
    loop = asyncio.get_running_loop()
    return _locks.setdefault(loop, asyncio.Lock())


def request_hash(decisions, edits, edited_text, policy, manual=None) -> str:
    return hashlib.sha256(json.dumps(
        [decisions, edits or {}, edited_text, policy, manual or []], sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()


def state(row):
    report = db.get_report(row['report_id']) if row['report_id'] else None
    return json.loads(report['maintenance_plan'] or '{}') if report else {}


def enqueue(settings, policy_store, submission_id, decisions, *, session_id,
            provider, edits=None, edited_text=None, manual=None):
    from . import submissions
    from .review import resolve_findings, readback_snapshot

    row = db.get_submission(submission_id)
    if not row:
        raise submissions.SubmissionError('提交不存在或已处理')
    if session_id != row['session_id'] or db.session_mode(session_id) != db.SESSION_MAINTAIN:
        raise submissions.SubmissionError('仅所属维护会话可以开始维护')
    existing = db.task_for_report(row['report_id'])
    if existing:
        return {'submission_id': submission_id, 'task_id': existing['id'], 'report_id': row['report_id']}
    if row['status'] != 'waiting':
        raise submissions.SubmissionError('提交不存在或已处理')
    if provider is None:
        raise submissions.SubmissionError('请先配置知识库模型')
    payload = submissions._decrypt(settings, row)
    if payload.get('documents') and edited_text is not None:
        raise submissions.SubmissionError('文件审查请使用选区保护和名称编辑，不支持整体替换正文')
    findings, instructions = resolve_findings(payload, manual)
    dec = validate_decisions(findings + instructions, decisions)
    file_entries, instr_entries = entries.build_all_entries(findings, instructions, dec, edits, namespace=payload['sha256'],
                              policy=payload.get('policy') or policy_store.load(),
                              sources={f.id: '整理要求' for f in instructions}, documents=payload.get('documents'))
    draft = dict(decisions=dec, edits=edits or {}, edited_text=edited_text, manual=manual or [])
    fingerprint = request_hash(dec, edits, edited_text, policy_store.load(), manual)
    payload['plan_draft'] = draft
    queued = dict(status='queued', request_hash=fingerprint)
    blob = crypto.seal(settings.queue_key(), json.dumps(payload, ensure_ascii=False).encode())
    snapshot = readback_snapshot(payload, file_entries, instr_entries) if edited_text is None else {}
    task_id = db.queue_submission_plan(submission_id, blob, json.dumps(queued), json.dumps(snapshot, ensure_ascii=False))
    if task_id is None:
        raise submissions.SubmissionError('提交不存在或已处理')
    return {'submission_id': submission_id, 'task_id': task_id, 'report_id': row['report_id']}


def fail(row, message):
    current = db.get_submission(row['id'])
    task = db.task_for_report(row['report_id'])
    if task and task['status'] not in ('done', 'failed'):
        db.update_task_status(task['id'], 'failed', error=message)
    if current and current['status'] in ('waiting', 'processing'):
        report = db.get_report(row['report_id'])
        if report and report['status'] == 'pending':
            db.update_report(row['report_id'], status='confirmed' if task else None,
                             maintenance_plan=json.dumps({'status': 'failed', 'error': message}, ensure_ascii=False))
        if task:
            db.resolve_submission(row['id'], 'failed')


def recover_interrupted():
    for row in db.list_submissions('processing'):
        task = db.task_for_report(row['report_id'])
        if task and task['status'] != 'planning_pending':
            fail(row, '服务重启，维护任务已中断，请重新发起维护。')
    # 旧版只确认了“生成计划”的提交不自动执行维护。
    for row in db.list_submissions('waiting'):
        if state(row).get('status') in ('queued', 'generating'):
            fail(row, '流程已更新，请审查资料并确认开始维护。')


def failure_message(error):
    # 只输出固定类别，不记录上游响应、模型原文、URL 或密钥。
    import httpx
    from ..llm.provider import LLMError
    from ..credentials.base import CredentialError
    from .submissions import SubmissionError

    cause = error
    while cause:
        if isinstance(cause, ToolBudgetExceeded):
            return '本次读取的知识库内容超过容量限制，已停止维护。请缩小本轮维护范围。'
        if isinstance(cause, compiler.PlanValidationError):
            return compiler.PlanValidationError.MESSAGES[cause.code]
        if isinstance(cause, GateBlockedError):
            return '脱敏后仍检测到未处置的敏感内容，已停止维护。请重新提交并审查资料。'
        if isinstance(cause, (httpx.TimeoutException, TimeoutError)):
            return '模型响应超时，请重新发起维护。'
        if isinstance(cause, httpx.HTTPStatusError):
            code = cause.response.status_code
            if code in (401, 403):
                return '模型认证失败，请检查模型配置。'
            if code == 429:
                return '模型服务请求受限，请稍后重新发起维护。'
            return '模型服务返回错误，请检查模型服务后重新发起维护。'
        if isinstance(cause, httpx.RequestError):
            return '模型连接失败，请检查模型服务后重新发起维护。'
        cause = cause.__cause__
    if isinstance(error, CredentialError):
        return '保险柜保存失败，本轮已停止并回滚；请检查保险柜配置和连接。'
    if isinstance(error, LLMError):
        if getattr(error, 'code', '') == 'reasoning_only':
            return '模型只返回了推理过程，没有返回可执行的维护计划。请重新发起维护。'
        if getattr(error, 'code', '') == 'output_limit':
            return '模型输出达到长度上限，计划未生成完整。请重新发起维护。'
        return '模型未返回有效计划，请重新发起维护。'
    if isinstance(error, compiler.PlanChangedError):
        return 'Wiki 已变化，请重新发起维护。'
    if isinstance(error, (SubmissionError, ValueError)):
        return '安全检查或计划校验未通过，请重新发起维护。'
    return '维护计划生成异常，请重新发起维护。'


async def process_pending(settings, policy_store, provider_getter, security_provider_getter, creds, run_task):
    from . import submissions
    for row in reversed(db.list_submissions('processing')):
        task = db.task_for_report(row['report_id'])
        if not task or task['status'] != 'planning_pending':
            continue
        tx = None
        token = None
        try:
            draft = submissions._decrypt(settings, row)['plan_draft']
            queued = state(row)
            if queued['request_hash'] != request_hash(draft['decisions'], draft['edits'], draft['edited_text'], policy_store.load(), draft['manual']):
                fail(row, '安全策略已变化，请重新发起维护。')
                continue
            queued['status'] = 'generating'
            db.update_report(row['report_id'], maintenance_plan=json.dumps(queued))
            db.update_task_status(task['id'], 'planning')
            async with asyncio.timeout(600):
                prepared = await prepare(settings, policy_store, row['id'], **draft,
                                        session_id=row['session_id'], provider=provider_getter(),
                                        security_provider=security_provider_getter(),
                                        on_progress=lambda: db.update_task_status(task['id'], 'drafting'))
                tx = transaction.Transaction(settings, creds, task['id'])
                token = transaction.active.set(tx)
                db.update_task_status(task['id'], 'saving')
                result = await submissions.confirm(
                    settings, creds, policy_store, row['id'], **draft,
                    session_id=row['session_id'], knowledge_provider_getter=provider_getter,
                    security_provider=security_provider_getter(), plan_token=prepared['plan_token'],
                    require_plan=True, task_id=task['id'])
                if result.get('duplicate'):
                    db.bind_task_source(task['id'], result['source_id'], '{}')
                    db.set_task_result(task['id'], json.dumps({'changes': [], 'duplicate': True}))
                    db.update_task_status(task['id'], 'done')
                else:
                    await run_task(task['id'], provider_getter())
                if db.get_task(task['id'])['status'] != 'done':
                    await tx.rollback()
                    if db.get_task(task['id'])['status'] != 'failed':
                        db.update_task_status(task['id'], 'failed', error='维护未完成，本轮保存已回滚。')
                else:
                    tx.commit()
        except (Exception, asyncio.CancelledError) as error:
            if tx is not None and db.get_task(task['id'])['status'] == 'done':
                # done 是持久化提交标记；只需重试清理日志，不能撤销已经提交的知识。
                db.log_security('transaction_cleanup_pending', f"任务 #{task['id']} 已完成，等待清理事务日志")
                return
            if tx is not None:
                try:
                    await asyncio.shield(tx.rollback())
                except Exception:
                    fail(row, '维护失败，补偿清理尚未完成；后续维护已暂停。')
                    db.update_task_status(task['id'], 'failed', error='维护失败，补偿清理尚未完成；后续维护已暂停。')
                    db.log_security('rollback_failed', f"任务 #{task['id']} 补偿未完成")
                    return
            if isinstance(error, asyncio.CancelledError):
                fail(row, '服务停止，本轮维护已回滚。')
                raise
            # 已完成保存时由 run_task 记录执行失败；这里处理生成/保存阶段失败。
            fail(row, failure_message(error))
            # 只记录代码位置，不记录异常消息或模型正文，便于定位后续失败。
            cause = error
            while cause.__cause__ is not None:
                cause = cause.__cause__
            frames = traceback.extract_tb(cause.__traceback__)
            origin = frames[-1] if frames else None
            location = f"{origin.name}:{origin.lineno}" if origin else 'unknown'
            db.log_security('maintenance_failed', f"任务 #{task['id']} 失败: {type(error).__name__} at {location}")
        finally:
            if token is not None:
                transaction.active.reset(token)


def checked_plan(settings, policy_store, row, decisions, edits, edited_text, token, manual=None):
    from .submissions import SubmissionError

    report = db.get_report(row['report_id']) if row['report_id'] else None
    prepared = json.loads(report['maintenance_plan'] or '{}') if report else {}
    if not token or prepared.get('token') != token:
        raise SubmissionError('请先生成并核对维护计划')
    if prepared.get('request_hash') != request_hash(decisions, edits, edited_text, policy_store.load(), manual):
        raise SubmissionError('报告或安全策略已修改，请更新维护计划后再确认')
    if prepared['wiki_revision'] != compiler.wiki_revision(settings):
        raise SubmissionError('Wiki 已变化，请更新维护计划后再确认')
    return prepared


async def prepare(settings, policy_store, submission_id, decisions, *, session_id,
                  provider, edits=None, edited_text=None, security_provider=None, manual=None, on_progress=None):
    from . import submissions

    row = db.get_submission(submission_id)
    if not row or row['status'] != 'processing':
        raise submissions.SubmissionError('提交不存在或已处理')
    if session_id != row['session_id']:
        raise submissions.SubmissionError('仅所属维护会话可以开始维护')
    if provider is None:
        raise submissions.SubmissionError('未配置知识库模型，无法生成维护计划')
    payload = submissions._decrypt(settings, row)
    from .review import resolve_findings, readback_snapshot

    findings, instr_findings = resolve_findings(payload, manual)
    current_policy = policy_store.load()
    snapshot_policy = payload.get('policy') or current_policy
    dec = validate_decisions(findings + instr_findings, decisions)
    sources = {f.id: '整理要求' for f in instr_findings}
    file_entries, instr_entries = entries.build_all_entries(
        findings, instr_findings, dec, edits, namespace=payload['sha256'],
        policy=snapshot_policy, sources=sources, documents=payload.get('documents'),
    )
    all_entries = file_entries + instr_entries
    preview, allowed = entries.apply_entries(payload['text'], file_entries)
    if edited_text is not None:
        if not isinstance(edited_text, str) or not edited_text.strip():
            raise submissions.SubmissionError('修改后的脱敏内容为空')
        if len(edited_text) > settings.max_upload_mb * 1024 * 1024:
            raise submissions.SubmissionError('修改后的脱敏内容超过上传上限')
        preview = edited_text
        allowed = locate_allow_spans(preview, findings, dec)
    instruction, instr_allowed = entries.apply_entries(payload.get('instruction') or '', instr_entries)
    # 提交时及当前策略都必须通过；模型规划前不允许未处置片段离开本机。
    for policy in (snapshot_policy, current_policy):
        engine = ScanEngine(policy, security_provider=security_provider)
        await rescan_guard(engine, preview, allowed, entries=all_entries)
        await rescan_guard(engine, instruction, instr_allowed, entries=all_entries)
    # 编辑过的全文只有复扫通过后才可持久化；模型失败也保留已审查快照。
    db.update_report(row['report_id'], review_snapshot=json.dumps(
        readback_snapshot(payload, file_entries, instr_entries, edited_text), ensure_ascii=False))
    valid = {p for e in all_entries if (p := entries._placeholder(e)) is not None}
    # 标记误报尚未最终确认时也不将命中原值送模型；计划先依据安全版本生成。
    model_text, _ = redactor.sanitize_llm_output(preview, policy=snapshot_policy, valid=valid)
    model_instruction, _ = redactor.sanitize_llm_output(instruction, policy=snapshot_policy, valid=valid)
    model_text, _ = redactor.sanitize_llm_output(model_text, policy=current_policy, valid=valid)
    model_instruction, _ = redactor.sanitize_llm_output(model_instruction, policy=current_policy, valid=valid)
    if payload.get('documents'):
        from .review import build_documents
        model_text = "\n\n".join(f"## 来源：{d['name']}\n{d['preview']}"
                                   for d in build_documents(payload, file_entries, []) if d['id'] != 'instruction')
        for policy in (snapshot_policy, current_policy):
            model_text, _ = redactor.sanitize_llm_output(model_text, policy=policy, valid=valid)
    task = db.task_for_report(row['report_id'])
    history = compiler.maintenance_context(settings, session_id, task['id'] if task else None)
    try:
        prepared = await compiler.generate_plan(settings, provider, model_text, model_instruction, valid_refs=valid, on_progress=on_progress, history=history)
    except (compiler.PlanChangedError, compiler.PlanValidationError):
        raise
    except (ValueError, TypeError, AttributeError) as e:
        # 不把模型生成的非法动作/路径原文作为错误信息返回。
        raise compiler.PlanValidationError() from e
    # 模型调用期间拒绝/过期、策略修改时，不把过期计划写回。
    latest = db.get_submission(submission_id)
    if not latest or latest['status'] != 'processing' or policy_store.load() != current_policy:
        raise submissions.SubmissionError('提交或安全策略已变化，请重新打开报告')
    prepared.update(status='ready', token=uuid.uuid4().hex, request_hash=request_hash(dec, edits, edited_text, current_policy, manual))
    db.update_report(row['report_id'], maintenance_plan=json.dumps(prepared, ensure_ascii=False),
                     preview=preview, instruction=instruction)
    return {'plan_token': prepared['token'], 'maintenance_plan': prepared['plan'],
            'preview': preview, 'instruction': instruction}
