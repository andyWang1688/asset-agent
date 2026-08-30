import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { toast } from 'sonner'
import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageShell, SegmentedControl, springTransition, staggerTransition } from '@/components/layout'
import { useApp } from '@/store/app-state'
import { useChat } from '@/hooks/use-chat'
import { useSubmissions, useTaskWatch } from '@/hooks/use-submissions'
import { useTypewriter } from '@/hooks/use-typewriter'
import { api, errMsg } from '@/lib/api'
import type { IngestResult, SubmissionView } from '@/lib/types'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Composer, type ChatMode } from './composer'
import { ConfirmSheet } from './confirm-sheet'
import { MessageList } from './message-list'
import { HistoryPanel } from '@/components/history-panel'

/** ingest 的待确认响应本身就是完整确认视图（submissions.view 展开） */
function viewFromIngest(r: IngestResult): SubmissionView {
  return r as unknown as SubmissionView
}

interface MtTask {
  id: number
  name: string
  status: string
  error: string | null
}

const MT_STATES = ['接收', '识别', '归类', '编译'] as const

function baseStep(status: string): number {
  switch (status) {
    case 'done':
      return 4
    case 'credential_pending':
      return 2
    case 'failed':
      return 1
    case 'processing':
      return 1
    default:
      return 0
  }
}

function mtLabel(status: string, step: number): string {
  switch (status) {
    case 'done':
      return '完成'
    case 'failed':
      return '失败'
    case 'credential_pending':
      return '凭证暂存'
    default:
      return MT_STATES[Math.min(step, 3)]
  }
}

/** 单行整理任务：四个状态点 + 状态文案；processing 期间自动推进 识别→归类→编译 */
function MtRow({ task }: { task: MtTask }) {
  const [step, setStep] = useState(() => baseStep(task.status))

  useEffect(() => {
    setStep(baseStep(task.status))
  }, [task.status])

  useEffect(() => {
    if (task.status !== 'processing' || step >= 3) return
    const t = window.setTimeout(() => setStep((s) => Math.min(3, s + 1)), 4000)
    return () => window.clearTimeout(t)
  }, [task.status, step])

  const hold = task.status === 'credential_pending' || task.status === 'failed'
  return (
    <div className="flex items-center gap-3 border-t border-border py-2.5 text-caption first:border-t-0" title={task.error || undefined}>
      <span className="min-w-0 flex-1 truncate font-semibold">{task.name}</span>
      <span className="flex items-center gap-[5px]">
        {MT_STATES.map((_, i) => (
          <i
            key={i}
            className={cn(
              'motion-state h-dot w-dot rounded-pill transition-colors',
              i < step ? 'bg-fg' : i === step ? (hold ? 'bg-fg' : 'animate-breathe bg-accent') : 'bg-border',
            )}
          />
        ))}
      </span>
      <span className="w-10 text-right font-mono text-meta text-muted">{mtLabel(task.status, step)}</span>
    </div>
  )
}

function TaskDrawer({ tasks, collecting, onClear }: { tasks: MtTask[]; collecting: boolean; onClear: () => void }) {
  const reduceMotion = useReducedMotion()
  return (
    <AnimatePresence initial={false}>
      {collecting && <motion.div className="w-[min(100%,720px)] shrink-0 overflow-hidden" initial={reduceMotion ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reduceMotion ? undefined : { height: 0, opacity: 0 }} transition={springTransition(reduceMotion)}>
      <motion.div className="motion-card mx-control mb-[calc(-1*var(--spacing-section))] rounded-lg border border-border bg-surface p-content shadow-panel" initial={reduceMotion ? false : { y: 'var(--spacing-content)', scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={reduceMotion ? undefined : { y: 'var(--spacing-content)', scale: 0.98 }} transition={springTransition(reduceMotion)}>
        <div className="mb-1 flex items-center justify-between">
          <span className="font-mono text-meta text-muted">整理任务</span>
          <button
            type="button"
            onClick={onClear}
            className="motion-interactive font-mono text-meta text-muted transition-colors hover:text-fg"
          >
            清除
          </button>
        </div>
        <AnimatePresence initial={false}>
        {tasks.map((t, index) => (
          <motion.div key={t.id} initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}><MtRow task={t} /></motion.div>
        ))}
        </AnimatePresence>
      </motion.div>
    </motion.div>}
    </AnimatePresence>
  )
}

const HINTS: Record<ChatMode, string[]> = {
  collect: ['整理一份投资记录', '归档保险合同', '提取房产资料'],
  ask: ['我有哪些待归档的资料？', '保险合同在哪个文件里？', '总结最近收录的内容'],
}

const TITLES: Record<ChatMode, { title: string; sub: string }> = {
  collect: {
    title: '收集并整理你的资产资料',
    sub: '粘贴内容或添加附件。我会创建整理任务，并标出待补充信息。',
  },
  ask: {
    title: '有什么可以帮你的？',
    sub: '询问已收录资料，或把新的资产资料交给我整理。',
  },
}

/** 流式标题/副标题：key 变化（切换模式或重新进入对话页）时重播打字效果 */
function StreamTitle({ k, text, speed }: { k: string; text: string; speed: number }) {
  const { shown, typing } = useTypewriter(text, speed)
  return (
    <h1 key={k} className={cn('text-display font-bold leading-tight', typing && 'streaming')}>
      {shown}
    </h1>
  )
}

function StreamSub({ k, text, speed }: { k: string; text: string; speed: number }) {
  const { shown, typing } = useTypewriter(text, speed)
  return (
    <p key={k} className={cn('mt-control text-caption leading-relaxed text-muted', typing && 'streaming')}>
      {shown}
    </p>
  )
}

export function ChatPage({ active, chat }: { active: boolean; chat: ReturnType<typeof useChat> }) {
  const { health, setTab } = useApp()
  const { messages, asking, ask, newChat, sessionTitle } = chat
  const { waiting, view, loadingView, load: loadSubs, openView, setViewDirect, closeView } = useSubmissions()
  const { watch } = useTaskWatch()

  const [mode, setMode] = useState<ChatMode>('ask')
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [pendingOpen, setPendingOpen] = useState(false)
  const [mtTasks, setMtTasks] = useState<MtTask[]>([])
  const [histOpen, setHistOpen] = useState(false)
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    if (!histOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHistOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [histOpen])

  const knowledgeMissing = !health || !health.knowledge_model
  const hasInput = value.trim().length > 0 || !!file
  const sendDisabled = knowledgeMissing || sending || asking || !hasInput
  const collecting = mode === 'collect' && mtTasks.length > 0
  const inSession = mode === 'ask' && messages.length > 0

  // 重新进入对话页时重播流式标题
  const [playKey, setPlayKey] = useState(0)
  const prevActive = useRef(active)
  useEffect(() => {
    if (active && !prevActive.current) setPlayKey((k) => k + 1)
    prevActive.current = active
  }, [active])
  const streamKey = `${mode}-${playKey}`

  const changeMode = useCallback((m: ChatMode) => {
    setMode(m)
    if (m === 'ask') setFile(null)
  }, [])

  // 结束（完成/失败）的任务保留 30 秒后自动从抽屉移除，也可手动清除
  useEffect(() => {
    if (!mtTasks.some((t) => t.status === 'done' || t.status === 'failed')) return
    const timer = window.setTimeout(() => {
      setMtTasks((prev) => prev.filter((t) => t.status !== 'done' && t.status !== 'failed'))
    }, 30000)
    return () => window.clearTimeout(timer)
  }, [mtTasks])

  const addTask = useCallback((id: number, name: string) => {
    const short = name.length > 16 ? name.slice(0, 16) + '…' : name
    // 新任务开始时清掉上一轮的终态行
    setMtTasks((prev) => [...prev.filter((t) => t.status !== 'done' && t.status !== 'failed'), { id, name: short, status: 'pending', error: null }])
  }, [])

  const startWatch = useCallback(
    (taskId: number) => {
      watch(taskId, (t) => {
        setMtTasks((prev) => prev.map((x) => (x.id === t.id ? { ...x, status: t.status, error: t.error } : x)))
        if (t.status === 'done') {
          toast.success('知识库整理完成')
        } else if (t.status === 'failed') {
          toast.error(`整理失败：${String(t.error || '未知错误').split('\n')[0]}`)
        }
      })
    },
    [watch],
  )

  const send = useCallback(async () => {
    if (sending || asking || sendDisabled) return
    setError('')

    if (mode === 'ask') {
      const err = await ask(value.trim())
      if (err) setError(err)
      else {
        setValue('')
        setFile(null)
      }
      return
    }

    setSending(true)
    try {
      const fd = new FormData()
      if (file) fd.append('file', file)
      else fd.append('text', value)
      const r = await api.ingest(fd)
      if (r.pending_confirmation) {
        setViewDirect(viewFromIngest(r))
      } else if (r.duplicate) {
        toast('内容已存在，未重复处理')
      } else {
        addTask(r.task_id, file ? file.name : value.trim())
        startWatch(r.task_id)
        toast.success(`已接收，来源 #${r.source_id}，任务 #${r.task_id}`)
        setValue('')
        setFile(null)
      }
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSending(false)
    }
  }, [sending, asking, sendDisabled, mode, ask, value, file, addTask, startWatch, setViewDirect])

  const openFromList = useCallback(
    async (id: number) => {
      await openView(id)
    },
    [openView],
  )

  const onConfirmed = useCallback(
    (r: IngestResult) => {
      closeView()
      addTask(r.task_id, file ? file.name : `提交 #${r.source_id}`)
      startWatch(r.task_id)
      void loadSubs()
      setValue('')
      setFile(null)
    },
    [closeView, addTask, startWatch, loadSubs, file],
  )

  const onCancelled = useCallback(() => {
    closeView()
    void loadSubs()
  }, [closeView, loadSubs])

  return (
    <PageShell className="h-full gap-0" contentClassName="h-full overflow-visible">
      {/* 对话历史是聊天页的上下文工具：仅出现在对话内容卡右上角 */}
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
      <div
        className={cn(
          // 高度由内容卡驱动（flex-1 撑满 PageShell 内容区），不再用 100vh 拍脑袋计算
          'flex h-full flex-col items-center px-0',
          collecting
            ? 'justify-end pb-section'
            : inSession
              ? 'justify-start pt-1 pb-compact'
              : 'justify-center py-section',
        )}
      >
        {inSession ? (
          <div className="flex w-[min(100%,760px)] shrink-0 items-center gap-2.5 py-4">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-panel font-semibold">{sessionTitle || messages[0].q}</h2>
              <small className="mt-0.5 block font-mono text-meta text-muted">询问知识 · {messages.length} 条</small>
            </div>
            <button
              type="button"
              onClick={newChat}
              className="motion-interactive inline-flex shrink-0 items-center gap-compact rounded-pill border border-border bg-surface px-control py-compact text-caption text-fg transition-[border-color,background,transform] hover:border-fg/30 hover:bg-soft active:scale-[0.97]"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                <path d="M12 5v14M5 12h14" />
              </svg>
              新对话
            </button>
          </div>
        ) : (
          <div className="mb-section text-center">
            <StreamTitle k={streamKey} text={TITLES[mode].title} speed={95} />
            <StreamSub k={streamKey + '-s'} text={TITLES[mode].sub} speed={32} />
            <SegmentedControl
              className="mt-content"
              label="对话模式"
              value={mode}
              options={[{ value: 'ask', label: '询问知识' }, { value: 'collect', label: '收集资料' }]}
              onChange={changeMode}
            />
          </div>
        )}

        {mode === 'ask' && messages.length > 0 && <MessageList messages={messages} asking={asking} />}

        <TaskDrawer tasks={mtTasks} collecting={collecting} onClear={() => setMtTasks([])} />

        <div className={cn('relative z-10 w-[min(100%,760px)] shrink-0', !inSession && 'mt-content', (inSession || collecting) && 'mt-auto')}>
          {knowledgeMissing && (
            <div className="mb-2 flex items-center justify-center gap-2 px-1 text-caption text-muted">
              <span>请先配置知识库模型</span>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setTab('settings')}>
                去设置
              </Button>
            </div>
          )}

          {waiting.length > 0 && (
            <div className="mb-2 flex flex-col items-center">
              <button
                type="button"
                onClick={() => setPendingOpen(!pendingOpen)}
                aria-expanded={pendingOpen}
                className="motion-interactive flex items-center gap-compact rounded-md px-compact py-1 text-caption text-muted transition-colors hover:bg-soft"
              >
                <span>待确认提交</span>
                <Badge variant="muted">{waiting.length}</Badge>
                <ChevronRight className={cn('motion-interactive h-3 w-3 transition-transform', pendingOpen && 'rotate-90')} />
              </button>
              <AnimatePresence initial={false}>
              {pendingOpen && (
                <motion.ul className="mt-1 max-h-[220px] w-full overflow-y-auto rounded-lg border border-border bg-surface shadow-panel" initial={reduceMotion ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reduceMotion ? undefined : { height: 0, opacity: 0 }} transition={springTransition(reduceMotion)}>
                  {waiting.map((s) => (
                    <li
                      key={s.id}
                      className="flex flex-wrap items-center gap-2.5 border-t border-border px-3.5 py-2 text-caption first:border-t-0"
                    >
                      <strong>#{s.id}</strong>
                      <span className="text-muted">{s.original_name || ''}</span>
                      <span className="text-muted">{fmtTime(s.created_at)}</span>
                      <Badge variant="err">凭证 {s.summary.credential || 0}</Badge>
                      <Badge variant="warn">个人信息 {s.summary.pii || 0}</Badge>
                      <Badge variant="muted">疑似 {s.summary.unknown_suspect || 0}</Badge>
                      <span className="flex-1" />
                      <Button variant="primary" size="sm" onClick={() => void openFromList(s.id)}>
                        打开确认
                      </Button>
                    </li>
                  ))}
                </motion.ul>
              )}
              </AnimatePresence>
            </div>
          )}

          <Composer
            mode={mode}
            value={value}
            onChange={setValue}
            onSend={() => void send()}
            sending={sending}
            sendDisabled={sendDisabled}
            fileName={file?.name ?? null}
            onFileChange={setFile}
          />

          {error && <p className="mt-2 text-center text-caption text-danger">{error}</p>}

          {!inSession && (
            <div className="mt-control flex flex-wrap justify-center gap-2">
              {HINTS[mode].map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setValue(h)}
                  className="motion-interactive rounded-pill border border-border bg-surface px-control py-compact text-caption text-muted transition-colors hover:border-fg hover:bg-soft hover:text-fg active:scale-[0.97]"
                >
                  {h}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <ConfirmSheet
        view={view}
        loading={loadingView}
        onClose={closeView}
        onConfirmed={(r) => onConfirmed(r)}
        onCancelled={onCancelled}
      />
      <HistoryPanel
        open={histOpen}
        activeSessionId={chat.sessionId}
        onClose={() => setHistOpen(false)}
        onOpenSession={(sid, msgs, title) => {
          chat.openSession(sid, msgs, title)
          setMode('ask')
          setHistOpen(false)
        }}
        onNewChat={() => {
          chat.newChat()
          setHistOpen(false)
        }}
      />
    </PageShell>
  )
}
