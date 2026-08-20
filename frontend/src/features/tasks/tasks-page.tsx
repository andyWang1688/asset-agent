import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTasks } from '@/hooks/use-tasks'
import { errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { TaskRow } from '@/lib/types'

const PAGE_SIZE = 5

type DotClass = 'processing' | 'waiting' | 'hold' | 'failed' | 'done'

function dotOf(status: string): DotClass {
  switch (status) {
    case 'processing':
      return 'processing'
    case 'credential_pending':
      return 'hold'
    case 'failed':
      return 'failed'
    case 'done':
      return 'done'
    default:
      return 'waiting'
  }
}

const DOT_CLASS: Record<DotClass, string> = {
  processing: 'animate-[breathe_1.4s_ease-in-out_infinite] bg-accent',
  waiting: 'bg-border',
  hold: 'bg-fg',
  failed: 'bg-fg',
  done: 'bg-fg',
}

function descOf(t: TaskRow): string {
  switch (t.status) {
    case 'processing':
      return '正在编译为 Wiki 页面'
    case 'credential_pending':
      return '凭证已加密暂存，等待凭证库恢复后继续'
    case 'failed':
      return String(t.error || '编译失败，未生成半成品 Wiki 页面').split('\n')[0].slice(0, 80)
    case 'done':
      return '已更新 Wiki'
    default:
      return '已通过确认闸门，等待后台处理'
  }
}

function stepsOf(status: string): string[] {
  switch (status) {
    case 'done':
      return ['done', 'done', 'done', 'done']
    case 'processing':
      return ['done', 'done', 'active', '']
    case 'credential_pending':
      return ['done', 'done', 'hold', '']
    case 'failed':
      return ['done', 'hold', '', '']
    default:
      return ['done', 'active', '', '']
  }
}

function TaskRowItem({ t, flashing, onRetry }: { t: TaskRow; flashing: boolean; onRetry?: (id: number) => void }) {
  const name = t.original_name || `来源 #${t.source_id}`
  const retryable = (t.status === 'failed' || t.status === 'credential_pending') && !!onRetry
  return (
    <div
      className={cn(
        'task-row grid grid-cols-[10px_minmax(0,1fr)_52px_125px_92px] items-center gap-3 border-b border-border px-[17px] py-4 last:border-b-0 max-[820px]:grid-cols-[10px_minmax(0,1fr)_74px]',
        flashing && 'animate-[requeue_1.1s_ease-out]',
      )}
    >
      <span className={cn('h-2.5 w-2.5 rounded-pill', DOT_CLASS[dotOf(t.status)])} title={t.status} />
      <div className="min-w-0">
        <strong className="block truncate text-caption font-semibold">{name}</strong>
        <small className="block truncate text-caption text-muted">{descOf(t)}</small>
      </div>
      <span className="flex items-center gap-[5px] max-[820px]:hidden">
        {stepsOf(t.status).map((c, i) => (
          <i
            key={i}
            className={cn(
              'h-[7px] w-[7px] rounded-pill',
              c === 'done' ? 'bg-fg' : c === 'active' ? 'animate-[breathe_1.4s_ease-in-out_infinite] bg-accent' : c === 'hold' ? 'bg-fg' : 'bg-border',
            )}
          />
        ))}
      </span>
      <span className="whitespace-nowrap font-mono text-meta text-muted max-[820px]:hidden">{`#${t.id} · ${t.status}`}</span>
      {retryable ? (
        <Button variant="compact" size="sm" className="justify-self-end" onClick={() => onRetry!(t.id)}>
          重试
        </Button>
      ) : (
        <span className="whitespace-nowrap text-right font-mono text-meta text-muted">{fmtTime(t.created_at)}</span>
      )}
    </div>
  )
}

export function TasksPage() {
  const { rows, attention, done, load, retry } = useTasks()
  const [helpOpen, setHelpOpen] = useState(false)
  const [page, setPage] = useState(0)
  const [flashId, setFlashId] = useState<number | null>(null)

  // 点击外部收起图例
  useEffect(() => {
    if (!helpOpen) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      if (!t.closest('[data-help-pop]') && !t.closest('[data-help-btn]')) setHelpOpen(false)
    }
    document.addEventListener('click', onDoc)
    return () => document.removeEventListener('click', onDoc)
  }, [helpOpen])

  const counts = useMemo(() => {
    const today = new Date().toDateString()
    return {
      processing: rows.filter((t) => t.status === 'processing').length,
      pending: rows.filter((t) => t.status === 'pending' || t.status === 'retry').length,
      retry: rows.filter((t) => t.status === 'credential_pending' || t.status === 'failed').length,
      doneToday: rows.filter((t) => t.status === 'done' && new Date(t.created_at).toDateString() === today).length,
    }
  }, [rows])

  // 队列排序：进行中的在前，完成的在后
  const queue = useMemo(
    () =>
      [...attention, ...done].sort((a, b) => {
        const aAct = a.status !== 'done' ? 0 : 1
        const bAct = b.status !== 'done' ? 0 : 1
        if (aAct !== bAct) return aAct - bAct
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      }),
    [attention, done],
  )
  const pages = Math.max(1, Math.ceil(queue.length / PAGE_SIZE))
  const pageRows = queue.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const lastDone = done[0]

  return (
    <>
      <h1 className="page-heading">任务</h1>
      <p className="page-sub">后台编译状态一览：任务由 Worker 推进，仅失败或凭证暂存的任务可重试。</p>

      <div className="mt-6 flex flex-wrap items-end justify-between gap-6 max-[480px]:flex-col max-[480px]:items-start max-[480px]:gap-2.5">
        <div className="flex flex-wrap gap-2">
          <span className="rounded-pill bg-soft px-2.5 py-[5px] font-mono text-meta text-muted">
            processing <b className="text-fg">{counts.processing}</b>
          </span>
          <span className="rounded-pill bg-soft px-2.5 py-[5px] font-mono text-meta text-muted">
            pending <b className="text-fg">{counts.pending}</b>
          </span>
          <span className="rounded-pill bg-soft px-2.5 py-[5px] font-mono text-meta text-muted">
            待重试 <b className="text-fg">{counts.retry}</b>
          </span>
          <span className="rounded-pill bg-soft px-2.5 py-[5px] font-mono text-meta text-muted">
            今日完成 <b className="text-fg">{counts.doneToday}</b>
          </span>
        </div>
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 text-caption"
          onClick={() => {
            void load()
            toast('任务列表已是最新')
          }}
        >
          刷新
        </Button>
      </div>

      <div className="mt-7 grid grid-cols-[minmax(0,1fr)_260px] items-start gap-4 max-[820px]:grid-cols-1">
        <section className="relative overflow-hidden rounded-lg border border-border bg-surface shadow-panel">
          <div className="flex items-center justify-between gap-3 border-b border-border px-[17px] py-[15px]">
            <h2 className="text-panel font-semibold">任务队列</h2>
            <div className="flex items-center gap-2">
              <Badge variant="accent">{queue.length}</Badge>
              <button
                type="button"
                data-help-btn
                aria-label="任务如何工作"
                onClick={(e) => {
                  e.stopPropagation()
                  setHelpOpen(!helpOpen)
                }}
                className="grid h-6 w-6 place-items-center rounded-pill bg-soft text-muted transition-colors duration-150 hover:bg-soft hover:text-fg"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-[13px] w-[13px]">
                  <circle cx="12" cy="12" r="8.5" />
                  <path d="M9.7 9.2a2.4 2.4 0 1 1 3.3 2.2c-.7.3-1 .8-1 1.6" />
                  <circle cx="12" cy="16.4" r=".6" fill="currentColor" stroke="none" />
                </svg>
              </button>
            </div>
          </div>

          <div
            data-help-pop
            className={cn(
              'absolute right-3.5 top-11 z-20 w-[264px] rounded-md border border-border bg-surface p-3.5 shadow-pop transition-[opacity,transform] duration-200 ease-out',
              helpOpen ? 'pointer-events-auto scale-100 opacity-100' : 'pointer-events-none translate-y-[-6px] scale-[0.98] opacity-0',
            )}
          >
            <p className="text-caption leading-[1.7] text-muted">
              任务状态由后台 Worker 更新，界面不提供人工完成或取消，避免状态与实际编译结果不一致。
            </p>
            <div className="mt-3 grid gap-[7px] text-caption text-muted">
              <div className="flex items-center gap-2">
                <i className="h-[7px] w-[7px] shrink-0 animate-[breathe_1.4s_ease-in-out_infinite] rounded-pill bg-accent" />
                processing · 编译中
              </div>
              <div className="flex items-center gap-2">
                <i className="h-[7px] w-[7px] shrink-0 rounded-pill bg-border" />
                pending · 排队等待
              </div>
              <div className="flex items-center gap-2">
                <i className="h-[7px] w-[7px] shrink-0 rounded-pill bg-fg" />
                credential_pending / failed · 可重试
              </div>
              <div className="flex items-center gap-2">
                <i className="h-[7px] w-[7px] shrink-0 rounded-pill bg-fg" />
                done · 已写入 Wiki
              </div>
            </div>
          </div>

          {pageRows.length === 0 && <p className="px-[17px] py-5 text-caption text-muted">暂无任务，一切正常。</p>}
          {pageRows.map((t) => (
            <TaskRowItem
              key={t.id}
              t={t}
              flashing={flashId === t.id}
              onRetry={(id) => {
                setFlashId(id)
                void retry(id)
                  .then(() => toast.success('任务已重新排队'))
                  .catch((e) => toast.error('重试失败：' + errMsg(e)))
                  .finally(() => window.setTimeout(() => setFlashId(null), 1200))
              }}
            />
          ))}

          <div className="flex items-center justify-end gap-2.5 border-t border-border px-[17px] py-3 max-[480px]:justify-center">
            <Button variant="compact" size="sm" disabled={page === 0} onClick={() => setPage(Math.max(0, page - 1))}>
              上一页
            </Button>
            <span className="font-mono text-meta text-muted">
              {page + 1} / {pages}
            </span>
            <Button variant="compact" size="sm" disabled={page >= pages - 1} onClick={() => setPage(Math.min(pages - 1, page + 1))}>
              下一页
            </Button>
          </div>
        </section>

        <aside className="rounded-lg border border-border bg-surface p-[17px] shadow-panel">
          <h2 className="text-panel font-semibold">最近完成</h2>
          {lastDone ? (
            <div className="mt-2.5 block text-caption text-muted">
              <b className="block font-semibold text-fg">{lastDone.original_name || `来源 #${lastDone.source_id}`}</b>
              任务 #{lastDone.id}，已写入 Wiki
            </div>
          ) : (
            <div className="mt-2.5 text-caption text-muted">暂无已完成任务</div>
          )}
        </aside>
      </div>
    </>
  )
}
