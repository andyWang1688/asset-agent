import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useIsMobile } from '@/hooks/use-is-mobile'
import type { ChatEntry } from '@/lib/types'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/hooks/use-chat'

interface HistoryPanelProps {
  open: boolean
  onClose: () => void
  onOpenSession: (sessionId: string, messages: ChatMessage[], title?: string | null) => void
  onNewChat: () => void
}

interface SessionGroup {
  id: string
  title: string
  time: string
  count: number
  pinned: boolean
  ids: number[]
  messages: ChatMessage[]
}

function dayLabel(time: string): string {
  const d = new Date(time.replace(' ', 'T'))
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.round((today.getTime() - day.getTime()) / 86400000)
  if (diff <= 0) return '今天'
  if (diff === 1) return '昨天'
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

/** 按 session_id 分组（旧数据无 session_id 时每条独立成会话），置顶优先、其余按最近活跃倒序 */
function groupSessions(rows: ChatEntry[]): SessionGroup[] {
  const map = new Map<string, ChatEntry[]>()
  for (const r of rows) {
    const key = r.session_id || `legacy-${r.id}`
    const list = map.get(key)
    if (list) list.push(r)
    else map.set(key, [r])
  }
  const groups: SessionGroup[] = []
  for (const [id, list] of map) {
    list.sort((a, b) => a.id - b.id)
    const first = list[0]
    const last = list[list.length - 1]
    const derived = first.question.length > 22 ? first.question.slice(0, 22) + '…' : first.question
    groups.push({
      id,
      title: first.title || derived,
      time: last.created_at,
      count: list.length,
      pinned: list[0].pinned,
      ids: list.map((r) => r.id),
      messages: list.map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })),
    })
  }
  groups.sort((a, b) => (a.pinned === b.pinned ? (a.time < b.time ? 1 : -1) : a.pinned ? -1 : 1))
  return groups
}

/** 对话历史滑入面板：会话列表（按日期分组、置顶优先），悬停三点菜单支持重命名/置顶/删除 */
export function HistoryPanel({ open, onClose, onOpenSession, onNewChat }: HistoryPanelProps) {
  const [groups, setGroups] = useState<SessionGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [confirmFor, setConfirmFor] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const isMobile = useIsMobile(820)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setGroups(groupSessions(await api.chatHistory()))
    } catch {
      setGroups([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setMenuFor(null)
      setConfirmFor(null)
      setRenaming(null)
      void load()
    }
  }, [open, load])

  const saveRename = async (id: string) => {
    const t = draft.trim()
    setRenaming(null)
    if (!t) return
    try {
      await api.setSessionTitle(id, t)
      await load()
    } catch {
      /* 忽略 */
    }
  }

  const togglePin = async (id: string, pinned: boolean) => {
    setMenuFor(null)
    try {
      await api.setSessionPin(id, !pinned)
      await load()
    } catch {
      /* 忽略 */
    }
  }

  const remove = async (id: string) => {
    setConfirmFor(null)
    setMenuFor(null)
    try {
      await api.deleteSession(id)
      await load()
    } catch {
      /* 忽略 */
    }
  }

  let lastDay = ''

  return (
    <aside
      aria-hidden={!open}
      className={
        'motion-spring fixed inset-y-0 right-0 z-40 flex w-[218px] max-w-[92vw] flex-col border-l border-border bg-surface shadow-pop transition-transform ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
    >
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-[15px]">
        <b className="min-w-0 flex-1 truncate text-panel">对话历史</b>
        <button
          type="button"
          aria-label="关闭历史"
          onClick={onClose}
          className="motion-interactive grid h-[26px] w-[26px] place-items-center rounded-sm text-muted transition-[color,background-color,transform] hover:bg-soft hover:text-fg active:scale-[0.97]"
        >
          ×
        </button>
      </div>
      <div className="border-b border-border p-2">
        <button
          type="button"
          onClick={onNewChat}
          className="motion-interactive flex w-full items-center justify-center gap-1.5 rounded-pill border border-border bg-surface px-3 py-[7px] text-caption font-semibold text-fg transition-[border-color,background,transform] hover:border-fg/30 hover:bg-soft active:scale-[0.97]"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
            <path d="M12 5v14M5 12h14" />
          </svg>
          开启新对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2" onClick={() => setMenuFor(null)}>
        {loading && groups.length === 0 ? (
          <p className="px-2.5 py-7 text-center text-caption text-muted">正在加载对话历史…</p>
        ) : groups.length === 0 ? (
          <p className="px-2.5 py-7 text-center text-caption text-muted">还没有对话记录，去提问吧。</p>
        ) : (
          groups.map((g) => {
            const day = g.pinned ? '置顶' : dayLabel(g.time)
            const showDay = day !== lastDay
            lastDay = day
            return (
              <div key={g.id}>
                {showDay && <div className="px-2.5 pb-1 pt-3 font-mono text-meta text-muted">{day}</div>}
                <div className="group relative">
                  {renaming === g.id ? (
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={() => void saveRename(g.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void saveRename(g.id)
                        if (e.key === 'Escape') setRenaming(null)
                      }}
                      aria-label="重命名会话"
                      className="mx-1 my-1 w-[calc(100%-8px)] rounded-sm border border-border bg-bg px-2 py-1.5 text-caption outline-none focus:border-fg/45"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        if (g.id.startsWith('legacy-')) void api.adoptSession(g.id, g.ids).catch(() => {})
                        onOpenSession(g.id, g.messages, g.title)
                        if (isMobile) onClose()
                      }}
                      className="motion-interactive block w-full rounded-md px-2.5 py-2.5 pr-8 text-left transition-colors hover:bg-soft active:scale-[0.97]"
                    >
                      <b className="block truncate text-caption font-semibold text-fg">{g.title}</b>
                      <small className="mt-0.5 block font-mono text-meta leading-[1.6] text-muted">
                        {fmtTime(g.time)} · {g.count} 条
                      </small>
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label="会话操作"
                    onClick={(e) => {
                      e.stopPropagation()
                      setMenuFor(menuFor === g.id ? null : g.id)
                      setConfirmFor(null)
                    }}
                    className={cn(
                      'motion-interactive absolute right-1.5 top-2 grid h-6 w-6 place-items-center rounded-sm text-muted transition-[opacity,background,color,transform] hover:bg-soft hover:text-fg active:scale-[0.97]',
                      menuFor === g.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
                    )}
                  >
                    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
                      <circle cx="5" cy="12" r="1.6" />
                      <circle cx="12" cy="12" r="1.6" />
                      <circle cx="19" cy="12" r="1.6" />
                    </svg>
                  </button>
                  {menuFor === g.id && (
                    <div
                      className="absolute right-2 top-9 z-30 w-[110px] rounded-md border border-border bg-surface p-1 shadow-pop"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {confirmFor === g.id ? (
                        <>
                          <button
                            type="button"
                            onClick={() => void remove(g.id)}
                            className="motion-interactive block w-full rounded-sm px-2 py-1.5 text-left text-caption font-semibold text-danger transition-colors hover:bg-danger-soft active:scale-[0.97]"
                          >
                            确认删除
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmFor(null)}
                            className="motion-interactive block w-full rounded-sm px-2 py-1.5 text-left text-caption text-muted transition-colors hover:bg-soft hover:text-fg active:scale-[0.97]"
                          >
                            取消
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => {
                              setRenaming(g.id)
                              setDraft(g.title)
                              setMenuFor(null)
                            }}
                            className="motion-interactive block w-full rounded-sm px-2 py-1.5 text-left text-caption text-fg transition-colors hover:bg-soft active:scale-[0.97]"
                          >
                            重命名
                          </button>
                          <button
                            type="button"
                            onClick={() => void togglePin(g.id, g.pinned)}
                            className="motion-interactive block w-full rounded-sm px-2 py-1.5 text-left text-caption text-fg transition-colors hover:bg-soft active:scale-[0.97]"
                          >
                            {g.pinned ? '取消置顶' : '置顶'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmFor(g.id)}
                            className="motion-interactive block w-full rounded-sm px-2 py-1.5 text-left text-caption text-danger transition-colors hover:bg-danger-soft active:scale-[0.97]"
                          >
                            删除
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
