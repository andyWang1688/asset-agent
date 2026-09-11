import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingState, PageShell, SegmentedControl } from '@/components/layout'
import { useApp } from '@/store/app-state'
import { useChat } from '@/hooks/use-chat'
import { useSubmissions } from '@/hooks/use-submissions'
import { useMaintenance } from '@/hooks/use-maintenance'
import { api, errMsg } from '@/lib/api'
import type { IngestResult, ReportSnapshot, SubmissionView, TaskRow } from '@/lib/types'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Composer, type ChatMode } from './composer'
import { ConfirmSheet } from './confirm-sheet'
import { MessageList } from './message-list'
import { HistoryPanel } from '@/components/history-panel'

/** ingest 的待确认响应本身就是完整确认视图 */
function viewFromIngest(r: IngestResult): SubmissionView {
  return r as unknown as SubmissionView
}

function taskState(status: string | null | undefined): 'processing' | 'done' | 'failed' | null {
  if (!status) return null
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  return 'processing' // pending / processing / credential_pending / retry 都属处理中
}

const TASK_STATE_LABEL: Record<'processing' | 'done' | 'failed', string> = {
  processing: '处理中',
  done: '成功',
  failed: '失败',
}

const HINTS: Record<ChatMode, string[]> = {
  ask: ['我有哪些待归档的资料？', '总结最近收录的内容', '某张保单在哪里？'],
  maintain: ['粘贴一段投资记录', '归档这份合同资料'],
}

/** 维护轮次：显示来源/脱敏预览/报告摘要/任务状态/失败原因；待确认可打开确认闸门 */
function RoundCard({ report, task, onConfirm }: { report: ReportSnapshot; task?: TaskRow; onConfirm?: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const state = taskState(task?.status)
  const statusBadge =
    report.status === 'pending' ? (
      <Badge variant="warn">待确认</Badge>
    ) : report.status === 'rejected' ? (
      <Badge variant="err">已拒绝</Badge>
    ) : report.status === 'auto' ? (
      <Badge variant="muted">自动处理</Badge>
    ) : (
      <Badge variant="ok">已确认</Badge>
    )
  return (
    <div className="rounded-lg border border-border bg-surface p-content shadow-panel">
      <div className="flex flex-wrap items-center gap-2">
        <b className="text-caption font-semibold">{report.original_name || '手动输入'}</b>
        {statusBadge}
        {state && <Badge variant={state === 'done' ? 'ok' : state === 'failed' ? 'err' : 'accent'}>{TASK_STATE_LABEL[state]}</Badge>}
        <span className="ml-auto font-mono text-meta text-muted">{fmtTime(report.created_at)}</span>
      </div>
      {report.instruction && <p className="mt-1.5 text-caption text-muted">整理要求：{report.instruction}</p>}
      <button type="button" className="motion-interactive mt-1.5 text-caption text-muted transition-colors hover:text-fg" onClick={() => setOpen((o) => !o)}>
        {open ? '收起内容' : '查看脱敏内容'}
      </button>
      {open && (
        <pre className="mt-2 max-h-[220px] whitespace-pre-wrap break-all rounded-md bg-soft p-2.5 font-mono text-caption leading-relaxed text-fg">{report.preview || '（无内容）'}</pre>
      )}
      {task?.error && <p className="mt-1.5 text-caption text-danger">失败原因：{String(task.error).split('\n')[0]}</p>}
      {report.status === 'pending' && report.submission_id != null && (
        <div className="mt-2.5">
          <Button variant="primary" size="sm" onClick={() => onConfirm?.(report.submission_id!)}>确认</Button>
        </div>
      )}
    </div>
  )
}

export function ChatPage({ chat }: { chat: ReturnType<typeof useChat> }) {
  const { health, setTab, pendingSession, consumeOpenSession } = useApp()
  const { messages, asking, ask, newChat, sessionTitle, sessionId, mode, draftMode, setDraftMode, openSession, openSessionById, hydrating } = chat

  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [histOpen, setHistOpen] = useState(false)
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId

  const isMaintain = mode === 'maintain'
  const maintenance = useMaintenance(isMaintain ? sessionId : null)
  const submissions = useSubmissions(isMaintain ? sessionId : null)

  useEffect(() => {
    if (pendingSession) {
      void openSessionById(pendingSession)
      consumeOpenSession()
    }
  }, [pendingSession, openSessionById, consumeOpenSession])

  useEffect(() => {
    if (!histOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setHistOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [histOpen])

  const knowledgeMissing = !health || !health.knowledge_model
  const activeMode: ChatMode = (mode ?? draftMode) as ChatMode
  const hasInput = value.trim().length > 0 || !!file
  const sendDisabled = knowledgeMissing || sending || asking || !hasInput

  const send = useCallback(async () => {
    if (sending || asking || sendDisabled) return
    setError('')
    const m = (mode ?? draftMode) as ChatMode
    if (m === 'ask') {
      const err = await ask(value.trim())
      if (err) setError(err)
      else { setValue(''); setFile(null) }
      return
    }
    setSending(true)
    try {
      const { sessionId: sid } = await chat.ensureSession('maintain')
      const fd = new FormData()
      fd.append('session_id', sid)
      if (file) {
        fd.append('file', file)
        if (value.trim()) fd.append('text', value)
      } else {
        fd.append('text', value)
      }
      const r = await api.ingest(fd)
      if (sessionIdRef.current !== sid) return // 会话已切换/新建，丢弃过期 ingest 结果
      if (r.pending_confirmation) {
        submissions.setViewDirect(viewFromIngest(r))
      } else if (r.duplicate) {
        toast('内容已存在，未重复处理')
      } else {
        toast.success(`已接收，来源 #${r.source_id}`)
      }
      setValue('')
      setFile(null)
      await Promise.all([maintenance.load(), submissions.load()])
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSending(false)
    }
  }, [sending, asking, sendDisabled, mode, draftMode, ask, value, file, chat, submissions, maintenance])

  const onConfirmed = useCallback((r: IngestResult) => {
    submissions.closeView()
    void Promise.all([maintenance.load(), submissions.load()])
    void r
  }, [submissions, maintenance])

  const onCancelled = useCallback(() => {
    submissions.closeView()
    void Promise.all([maintenance.load(), submissions.load()])
  }, [submissions, maintenance])

  const inSession = sessionId != null

  if (hydrating) {
    return <PageShell className="h-full"><LoadingState label="正在恢复会话…" className="h-full" /></PageShell>
  }

  return (
    <PageShell className="h-full gap-0" contentClassName="h-full overflow-visible">
      <button
        type="button"
        aria-label="对话历史"
        title="对话历史"
        onClick={() => setHistOpen(true)}
        className="motion-interactive absolute right-3 top-3 z-20 flex h-[34px] items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-muted shadow-panel transition-[color,background-color,transform] hover:bg-soft hover:text-fg active:scale-[0.97]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-[15px] w-[15px]">
          <path d="M4.5 5.5v4h4" />
          <path d="M5.2 9.5a7.5 7.5 0 1 1-1.2 4" />
          <path d="M12 8.5v4l2.6 1.6" />
        </svg>
        <span className="text-caption font-medium max-[820px]:hidden">历史</span>
      </button>

      <div className="flex h-full flex-col items-center px-0">
        {inSession ? (
          <div className="flex w-[min(100%,760px)] shrink-0 items-center gap-2.5 py-4">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-panel font-semibold">{sessionTitle || (isMaintain ? '资料维护' : messages[0]?.q || '对话')}</h2>
              <small className="mt-0.5 block font-mono text-meta text-muted">
                {isMaintain ? '维护' : '问答 · 只读'}
              </small>
            </div>
            <button type="button" onClick={newChat} className="motion-interactive inline-flex shrink-0 items-center gap-compact rounded-pill border border-border bg-surface px-control py-compact text-caption text-fg transition-[border-color,background,transform] hover:border-fg/30 hover:bg-soft active:scale-[0.97]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M12 5v14M5 12h14" /></svg>
              新对话
            </button>
          </div>
        ) : (
          <div className="mb-section mt-10 text-center">
            <h1 className="text-display font-bold leading-tight">开始一段对话</h1>
            <p className="mt-control text-caption leading-relaxed text-muted">选择对话方式：问答只读知识库，或维护并归档你的资产资料。</p>
            <SegmentedControl
              className="mt-content"
              label="对话模式"
              value={draftMode}
              options={[{ value: 'ask', label: '问答' }, { value: 'maintain', label: '维护' }]}
              onChange={(m) => setDraftMode(m as ChatMode)}
            />
          </div>
        )}

        {mode === 'ask' && <MessageList messages={messages} asking={asking} />}
        {isMaintain && (
          <div className="flex w-[min(100%,760px)] min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1 py-2">
            {maintenance.error && <p className="text-caption text-warn">获取维护记录失败，显示最近一次数据。</p>}
            {maintenance.loading && maintenance.reports.length === 0 ? (
              <p className="py-6 text-center text-caption text-muted">正在加载维护记录…</p>
            ) : maintenance.reports.length === 0 ? (
              <p className="py-6 text-center text-caption text-muted">还没有维护记录，粘贴资料或添加单个 TXT/Markdown 开始。</p>
            ) : (
              maintenance.reports.map((r) => (
                <RoundCard
                  key={r.id}
                  report={r}
                  task={maintenance.tasks.find((t) => t.report_id === r.id)}
                  onConfirm={(sid) => void submissions.openView(sid)}
                />
              ))
            )}
          </div>
        )}

        <div className={cn('relative z-10 w-[min(100%,760px)] shrink-0', inSession ? 'mt-auto pb-compact' : 'mt-content')}>
          {knowledgeMissing && (
            <div className="mb-2 flex items-center justify-center gap-2 px-1 text-caption text-muted">
              <span>请先配置知识库模型</span>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setTab('settings')}>去设置</Button>
            </div>
          )}

          <Composer
            mode={activeMode}
            value={value}
            onChange={setValue}
            onSend={() => void send()}
            sending={sending || asking}
            sendDisabled={sendDisabled}
            fileName={file?.name ?? null}
            onFileChange={setFile}
          />

          {error && <p className="mt-2 text-center text-caption text-danger">{error}</p>}

          {!inSession && (
            <div className="mt-control flex flex-wrap justify-center gap-2">
              {HINTS[activeMode].map((h) => (
                <button key={h} type="button" onClick={() => setValue(h)} className="motion-interactive rounded-pill border border-border bg-surface px-control py-compact text-caption text-muted transition-colors hover:border-fg hover:bg-soft hover:text-fg active:scale-[0.97]">
                  {h}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <ConfirmSheet
        view={submissions.view}
        loading={submissions.loadingView}
        onClose={submissions.closeView}
        onConfirmed={onConfirmed}
        onCancelled={onCancelled}
      />
      <HistoryPanel
        open={histOpen}
        activeSessionId={sessionId}
        onClose={() => setHistOpen(false)}
        onOpenSession={(sid, m, msgs, title) => {
          openSession(sid, m, msgs, title)
          setHistOpen(false)
        }}
        onNewChat={() => {
          newChat()
          setHistOpen(false)
        }}
      />
    </PageShell>
  )
}
