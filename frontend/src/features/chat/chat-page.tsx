import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useApp } from '@/store/app-context'
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
              'h-[7px] w-[7px] rounded-pill transition-colors duration-300',
              i < step ? 'bg-fg' : i === step ? (hold ? 'bg-fg' : 'animate-[breathe_1.4s_ease-in-out_infinite] bg-accent') : 'bg-border',
            )}
          />
        ))}
      </span>
      <span className="w-10 text-right font-mono text-meta text-muted">{mtLabel(task.status, step)}</span>
    </div>
  )
}

function TaskDrawer({ tasks, collecting }: { tasks: MtTask[]; collecting: boolean }) {
  return (
    <div
      className="w-[min(100%,720px)] overflow-hidden transition-[max-height,opacity,margin-bottom] duration-500 ease-out"
      style={collecting ? { maxHeight: 320, opacity: 1, marginBottom: -18 } : { maxHeight: 0, opacity: 0, marginBottom: 0 }}
    >
      <div
        className="mx-2.5 rounded-lg border border-border bg-surface px-[17px] pb-[19px] pt-[15px] shadow-panel transition-transform duration-500 ease-out"
        style={collecting ? undefined : { transform: 'translateY(14px) scale(0.98)' }}
      >
        {tasks.map((t) => (
          <MtRow key={t.id} task={t} />
        ))}
      </div>
    </div>
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
    <h1 key={k} className={cn('animate-[swap-in_0.3s_ease-out] text-[clamp(31px,4vw,46px)] font-bold leading-[1.2]', typing && 'streaming')}>
      {shown}
    </h1>
  )
}

function StreamSub({ k, text, speed }: { k: string; text: string; speed: number }) {
  const { shown, typing } = useTypewriter(text, speed)
  return (
    <p key={k} className={cn('mt-2.5 text-caption leading-[1.7] text-muted', typing && 'streaming')}>
      {shown}
    </p>
  )
}

export function ChatPage({ active }: { active: boolean }) {
  const { health, setTab } = useApp()
  const { messages, asking, ask } = useChat()
  const { waiting, view, loadingView, load: loadSubs, openView, setViewDirect, closeView } = useSubmissions()
  const { watch } = useTaskWatch()

  const [mode, setMode] = useState<ChatMode>('ask')
  const [value, setValue] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [pendingOpen, setPendingOpen] = useState(false)
  const [mtTasks, setMtTasks] = useState<MtTask[]>([])

  const knowledgeMissing = !health || !health.knowledge_model
  const hasInput = value.trim().length > 0 || !!file
  const sendDisabled = knowledgeMissing || sending || asking || !hasInput
  const collecting = mode === 'collect' && mtTasks.length > 0

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

  // 完成的任务停留 5 秒后自动从抽屉移除
  useEffect(() => {
    if (!mtTasks.some((t) => t.status === 'done')) return
    const timer = window.setTimeout(() => {
      setMtTasks((prev) => prev.filter((t) => t.status !== 'done'))
    }, 5000)
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
    <>
      <div
        className={cn(
          'flex min-h-[calc(100vh-164px)] flex-col items-center px-0 pb-[72px] pt-[30px] transition-[justify-content] duration-300 max-[820px]:min-h-[calc(100vh-140px)]',
          collecting ? 'justify-end pt-0' : 'justify-center',
        )}
      >
        <div className="mb-[30px] text-center">
          <StreamTitle k={streamKey} text={TITLES[mode].title} speed={95} />
          <StreamSub k={streamKey + '-s'} text={TITLES[mode].sub} speed={32} />
          <div className="relative mt-[18px] inline-flex gap-0.5 rounded-md border border-border bg-surface p-1" data-active={mode}>
            <span
              className={cn(
                'absolute bottom-1 left-1 top-1 w-[calc(50%-5px)] rounded-sm bg-fg transition-transform duration-300 ease-out',
                mode === 'collect' && 'translate-x-[calc(100%+2px)]',
              )}
            />
            <button
              type="button"
              className={cn('relative z-10 min-w-[88px] rounded-sm px-3.5 py-2 text-caption transition-colors duration-200', mode === 'ask' ? 'font-semibold text-surface' : 'text-muted')}
              onClick={() => changeMode('ask')}
            >
              询问知识
            </button>
            <button
              type="button"
              className={cn('relative z-10 min-w-[88px] rounded-sm px-3.5 py-2 text-caption transition-colors duration-200', mode === 'collect' ? 'font-semibold text-surface' : 'text-muted')}
              onClick={() => changeMode('collect')}
            >
              收集资料
            </button>
          </div>
        </div>

        {mode === 'ask' && messages.length > 0 && <MessageList messages={messages} asking={asking} />}

        <TaskDrawer tasks={mtTasks} collecting={collecting} />

        <div className="relative z-10 w-[min(100%,720px)]">
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
                className="flex items-center gap-2 rounded-md px-2 py-1 text-caption text-muted transition-colors duration-150 hover:bg-soft"
              >
                <span>待确认提交</span>
                <Badge variant="muted">{waiting.length}</Badge>
                <ChevronRight className={cn('h-3 w-3 transition-transform duration-200', pendingOpen && 'rotate-90')} />
              </button>
              {pendingOpen && (
                <ul className="mt-1 max-h-[220px] w-full overflow-y-auto rounded-lg border border-border bg-surface shadow-panel">
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
                </ul>
              )}
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

          <div className="mt-3.5 flex flex-wrap justify-center gap-2">
            {HINTS[mode].map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setValue(h)}
                className="rounded-pill border border-border bg-surface px-3.5 py-[7px] text-caption text-muted transition-colors duration-150 hover:border-fg hover:bg-soft hover:text-fg"
              >
                {h}
              </button>
            ))}
          </div>
        </div>
      </div>

      <ConfirmSheet
        view={view}
        loading={loadingView}
        onClose={closeView}
        onConfirmed={(r) => onConfirmed(r)}
        onCancelled={onCancelled}
      />
    </>
  )
}
