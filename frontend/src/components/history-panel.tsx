import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { ChatEntry } from '@/lib/types'
import { fmtTime } from '@/lib/format'
import { Markdown } from '@/lib/markdown'

interface HistoryPanelProps {
  open: boolean
  onClose: () => void
}

/** 对话历史滑入面板：右侧抽屉，列表 + 单条对话详情（/api/chat/history） */
export function HistoryPanel({ open, onClose }: HistoryPanelProps) {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<ChatEntry | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setEntries(await api.chatHistory())
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      void load()
      setDetail(null)
    }
  }, [open, load])

  return (
    <aside
      aria-hidden={!open}
      className={
        'fixed inset-y-0 right-0 z-40 flex w-[218px] max-w-[92vw] flex-col border-l border-border bg-surface shadow-pop transition-transform duration-500 ease-out ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
    >
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-[15px]">
        {detail && (
          <button
            type="button"
            aria-label="返回列表"
            onClick={() => setDetail(null)}
            className="grid h-[26px] w-[26px] place-items-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-fg"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
              <path d="m14 6-6 6 6 6" />
            </svg>
          </button>
        )}
        <b className="min-w-0 flex-1 truncate text-panel">{detail ? detail.question : '对话历史'}</b>
        <button
          type="button"
          aria-label="关闭历史"
          onClick={onClose}
          className="grid h-[26px] w-[26px] place-items-center rounded-sm text-muted transition-colors duration-150 hover:bg-soft hover:text-fg"
        >
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {detail ? (
          <div className="flex flex-col gap-2 p-1">
            <div className="rounded-md bg-fg px-2.5 py-2 text-caption leading-[1.6] text-surface">{detail.question}</div>
            <div className="rounded-md bg-soft px-2.5 py-2 text-caption leading-[1.6] text-fg">
              <Markdown content={detail.answer} />
            </div>
            {detail.citations?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {detail.citations.map((c) => (
                  <span key={c} className="rounded-sm border border-border bg-surface px-2 py-0.5 font-mono text-meta text-muted">
                    {c}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : loading && entries.length === 0 ? (
          <p className="px-2.5 py-7 text-center text-caption text-muted">正在加载对话历史…</p>
        ) : entries.length === 0 ? (
          <p className="px-2.5 py-7 text-center text-caption text-muted">还没有对话记录，去提问吧。</p>
        ) : (
          entries.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => setDetail(h)}
              className="block w-full rounded-md px-2.5 py-2.5 text-left transition-colors duration-150 hover:bg-soft"
            >
              <b className="block text-caption font-semibold text-fg">{h.question}</b>
              <small className="mt-0.5 block font-mono text-meta leading-[1.6] text-muted">{fmtTime(h.created_at)}</small>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
