import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { CheckCircle2, CircleAlert, CircleDashed } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useApp } from '@/store/app-state'
import { useChat } from '@/hooks/use-chat'
import { useSubmissions } from '@/hooks/use-submissions'
import { useMaintenance } from '@/hooks/use-maintenance'
import { api, errMsg } from '@/lib/api'
import type { IngestResult, MaintenanceReceipt, ReportSnapshot, SubmissionView, TaskRow } from '@/lib/types'
import { fmtTime } from '@/lib/format'
import { Composer, type ChatMode } from './composer'
import { ConfirmSheet } from './confirm-sheet'
import { MessageList } from './message-list'

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '')

/** ingest 的待确认响应本身就是完整确认视图 */
function viewFromIngest(r: IngestResult): SubmissionView {
  return r as unknown as SubmissionView
}

type TaskState = 'processing' | 'done' | 'failed' | null

function taskState(status: string | null | undefined): TaskState {
  if (!status) return null
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  return 'processing'
}

const TASK_STATE_LABEL: Record<'processing' | 'done' | 'failed', string> = {
  processing: '处理中',
  done: '成功',
  failed: '失败',
}

/** 维护轮次：来源/脱敏预览/报告摘要/任务状态/失败原因；待确认可打开确认闸门 */
export function RoundCard({ report, task, onConfirm }: { report: ReportSnapshot; task?: TaskRow; onConfirm?: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const state = taskState(task?.status)
  const { setTab } = useApp()
  const statusBadge =
    report.status === 'pending' && !task ? (
      <Badge className="border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-300">待确认</Badge>
    ) : report.status === 'rejected' ? (
      <Badge className="border-transparent bg-destructive/10 text-destructive">已拒绝</Badge>
    ) : report.status === 'auto' ? (
      <Badge variant="secondary">自动处理</Badge>
    ) : (
      <Badge className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">已确认</Badge>
    )
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <b className="max-w-full truncate text-sm font-semibold sm:max-w-80" title={report.original_name || '手动输入'}>{report.original_name || '手动输入'}</b>
        {statusBadge}
        {state && (
          <span className="inline-flex items-center gap-1.5">
            {state === 'done' && <CheckCircle2 className="size-3.5 text-emerald-600" />}
            {state === 'failed' && <CircleAlert className="size-3.5 text-destructive" />}
            {state === 'processing' && <CircleDashed className="size-3.5 animate-spin text-muted-foreground [animation-duration:3s]" />}
            <span className="text-xs text-muted-foreground">{TASK_STATE_LABEL[state]}</span>
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{fmtTime(report.created_at)}</span>
      </div>
      {report.instruction && <p className="mt-1.5 text-xs text-muted-foreground">整理要求：{report.instruction}</p>}
      <button type="button" className="mt-2 text-xs text-muted-foreground transition-colors hover:text-foreground" onClick={() => setOpen((o) => !o)}>
        {open ? '收起内容' : '查看脱敏内容'}
      </button>
      {open && (
        <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed">{report.preview || '（无内容）'}</pre>
      )}
      {!task && report.status === 'pending' && report.plan_error && <p role="alert" className="mt-2 text-xs text-destructive">{report.plan_error}</p>}
      {task?.error && <p className="mt-2 text-xs text-destructive">失败原因：{String(task.error).split('\n')[0]}</p>}
      {task && <Button variant="outline" size="sm" className="mt-3" onClick={() => setTab('tasks')}>查看任务 #{task.id}</Button>}
      {!task && report.status === 'pending' && report.submission_id != null && (
        <div className="mt-3">
          <Button size="sm" className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => onConfirm?.(report.submission_id!)}>
            继续审查
          </Button>
        </div>
      )}
    </div>
  )
}

function ChatEmpty({
  mode,
  onModeChange,
  value,
  onChange,
  onSend,
  sending,
  sendDisabled,
  files,
  onFileChange,
  knowledgeMissing,
  onGoSettings,
  error,
  focusToken,
}: {
  mode: ChatMode
  onModeChange: (m: ChatMode) => void
  value: string
  onChange: (v: string) => void
  onSend: () => void
  sending: boolean
  sendDisabled: boolean
  files: File[]
  onFileChange: (f: File[]) => void
  knowledgeMissing: boolean
  onGoSettings: () => void
  error: string
  focusToken: number
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4">
      <h1 className="mt-8 text-center text-4xl font-semibold tracking-tight">
        {mode === 'ask' ? '想问点什么？' : '今天想整理点什么？'}
      </h1>
      <p className="mt-3 text-center text-base text-muted-foreground">
        {mode === 'ask' ? '问答只读知识库，不会修改任何内容。' : '粘贴资料或添加文件，安全处理后归档进知识库。'}
      </p>
      <div className="mt-10 w-full max-w-3xl">
        <Composer
          mode={mode}
          value={value}
          onChange={onChange}
          onSend={onSend}
          sending={sending}
          sendDisabled={sendDisabled}
          files={files}
          onFileChange={onFileChange}
          showModeSwitch
          onModeChange={onModeChange}
          large
          focusToken={focusToken}
        />
      </div>
      <p className="mt-3 text-center text-xs text-muted-foreground">
        Enter 发送 · Shift + Enter 换行 · {IS_MAC ? '⌘K' : 'Ctrl+K'} 聚焦输入框
      </p>
      {error && <p className="mt-3 text-center text-xs text-destructive">{error}</p>}
      {knowledgeMissing && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <span>请先配置知识库模型</span>
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onGoSettings}>
            去设置
          </Button>
        </div>
      )}
    </div>
  )
}

/** 对话页：新对话空状态（模式在输入框内）+ 问答消息流 / 维护轮次 + 确认闸门 */
export function ChatPage({ chat }: { chat: ReturnType<typeof useChat> }) {
  const { health, navigateSettings, pendingSession, consumeOpenSession, setTab } = useApp()
  const { messages, asking, ask, sessionId, mode, draftMode, setDraftMode, openSessionById, hydrating } = chat

  const [value, setValue] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [focusToken, setFocusToken] = useState(0)
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

  // 常用快捷键：⌘/Ctrl+K 聚焦输入框；⌘/Ctrl+Shift+O 新对话
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (!mod) return
      const key = e.key.toLowerCase()
      if (key === 'k') {
        e.preventDefault()
        setFocusToken((n) => n + 1)
      } else if (e.shiftKey && key === 'o') {
        e.preventDefault()
        chat.newChat()
        setFocusToken((n) => n + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [chat])

  const knowledgeMissing = !health || !health.knowledge_model
  const activeMode: ChatMode = (mode ?? draftMode) as ChatMode
  const hasInput = value.trim().length > 0 || (activeMode === 'maintain' && files.length > 0)
  const sendDisabled = knowledgeMissing || sending || asking || !hasInput

  const send = useCallback(async () => {
    if (sending || asking || sendDisabled) return
    setError('')
    const m = (mode ?? draftMode) as ChatMode
    if (m === 'ask') {
      const err = await ask(value.trim())
      if (err) setError(err)
      else {
        setValue('')
        setFiles([])
      }
      return
    }
    setSending(true)
    try {
      const { sessionId: sid } = await chat.ensureSession('maintain')
      const fd = new FormData()
      fd.append('session_id', sid)
      if (files.length) {
        files.forEach((file) => fd.append('files', file))
        if (value.trim()) fd.append('text', value)
      } else {
        fd.append('text', value)
      }
      const r = await api.ingest(fd)
      if (sessionIdRef.current !== sid) return
      if (r.pending_confirmation) {
        submissions.setViewDirect(viewFromIngest(r))
      } else if (r.duplicate) {
        toast('内容已存在，未重复处理')
      } else {
        toast.success(`已创建维护任务 #${r.task_id}`)
      }
      setValue('')
      setFiles([])
      await Promise.all([maintenance.load(), submissions.load()])
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSending(false)
    }
  }, [sending, asking, sendDisabled, mode, draftMode, ask, value, files, chat, submissions, maintenance])

  const onConfirmed = useCallback(
    (r: MaintenanceReceipt) => {
      submissions.closeView()
      setTab('tasks')
      void Promise.all([maintenance.load(), submissions.load()])
      void r
    },
    [submissions, maintenance, setTab],
  )

  const onCancelled = useCallback(() => {
    submissions.closeView()
    void Promise.all([maintenance.load(), submissions.load()])
  }, [submissions, maintenance])

  if (hydrating) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24 w-full max-w-3xl rounded-xl" />
        <Skeleton className="h-24 w-full max-w-3xl rounded-xl" />
      </div>
    )
  }

  const inSession = sessionId != null

  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-col">
      {!inSession ? (
        <ChatEmpty
          mode={draftMode}
          onModeChange={setDraftMode}
          value={value}
          onChange={setValue}
          onSend={() => void send()}
          sending={sending || asking}
          sendDisabled={sendDisabled}
          files={files}
          onFileChange={setFiles}
          knowledgeMissing={knowledgeMissing}
          onGoSettings={() => navigateSettings('models')}
          error={error}
          focusToken={focusToken}
        />
      ) : (
        <>
          {mode === 'ask' ? (
            <MessageList messages={messages} asking={asking} />
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <div className="mx-auto flex w-[min(100%,760px)] flex-col gap-3">
                {maintenance.error && <p className="text-xs text-amber-600">获取维护记录失败，显示最近一次数据。</p>}
                {maintenance.loading && maintenance.reports.length === 0 ? (
                  <>
                    <Skeleton className="h-28 w-full rounded-xl" />
                    <Skeleton className="h-28 w-full rounded-xl" />
                  </>
                ) : maintenance.reports.length === 0 ? (
                  <p className="py-6 text-center text-xs text-muted-foreground">还没有维护记录，粘贴资料或添加单个 TXT/Markdown 开始。</p>
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
            </div>
          )}

          <div className="shrink-0 px-4 pb-4 pt-2">
            <div className="mx-auto w-[min(100%,760px)]">
              {knowledgeMissing && (
                <div className="mb-2 flex items-center justify-center gap-2 text-xs text-muted-foreground">
                  <span>请先配置知识库模型</span>
                  <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => navigateSettings('models')}>
                    去设置
                  </Button>
                </div>
              )}
              <Composer
                mode={activeMode}
                value={value}
                onChange={setValue}
                onSend={() => void send()}
                sending={sending || asking}
                sendDisabled={sendDisabled}
                files={files}
                onFileChange={setFiles}
                focusToken={focusToken}
              />
              {error && <p className="mt-2 text-center text-xs text-destructive">{error}</p>}
            </div>
          </div>
        </>
      )}

      <ConfirmSheet
        view={submissions.view}
        loading={submissions.loadingView}
        onClose={submissions.closeView}
        onConfirmed={onConfirmed}
        onCancelled={onCancelled}
      />
    </div>
  )
}
