import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState, PageShell, SectionCard } from '@/components/layout'
import { useTasks } from '@/hooks/use-tasks'
import { useApp } from '@/store/app-state'
import { api } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ReportSnapshot, TaskRow } from '@/lib/types'

type TaskState = 'processing' | 'done' | 'failed'

function toState(status: string): TaskState {
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  return 'processing' // pending / processing / credential_pending / retry
}

const STATE_META: Record<TaskState, { label: string; variant: 'accent' | 'ok' | 'err' }> = {
  processing: { label: '处理中', variant: 'accent' },
  done: { label: '成功', variant: 'ok' },
  failed: { label: '失败', variant: 'err' },
}

function TaskDetail({ task, onBack, onClose }: { task: TaskRow; onBack: (sessionId: string) => void; onClose: () => void }) {
  const [report, setReport] = useState<ReportSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const { openWikiDoc } = useApp()
  useEffect(() => {
    if (task.report_id == null) return
    let cancelled = false
    setLoading(true)
    void api
      .reportView(task.report_id)
      .then((r) => { if (!cancelled) setReport(r) })
      .catch(() => { if (!cancelled) setReport(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [task.report_id])

  const state = toState(task.status)
  return (
    <SectionCard title={`任务 #${task.id} 详情`} className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={STATE_META[state].variant}>{STATE_META[state].label}</Badge>
        <span className="font-mono text-meta text-muted">{fmtTime(task.created_at)}</span>
        {task.session_id && (
          <Button variant="outline" size="sm" onClick={() => onBack(task.session_id!)}>回到原会话</Button>
        )}
      </div>
      {task.error && <p className="mt-3 rounded-md bg-danger-soft p-2.5 text-caption text-danger">失败原因：{task.error}</p>}
      {loading && <p className="mt-3 text-caption text-muted">正在加载报告快照…</p>}
      {report && (
        <div className="mt-3 grid gap-2">
          <div className="flex flex-wrap gap-2 text-caption">
            <Badge variant={report.status === 'rejected' ? 'err' : report.status === 'pending' ? 'warn' : 'muted'}>
              {report.status === 'rejected' ? '已拒绝' : report.status === 'pending' ? '待确认' : report.status === 'auto' ? '自动处理' : '已确认'}
            </Badge>
            <span className="text-muted">{report.original_name || '手动输入'}</span>
          </div>
          <pre className="max-h-[260px] whitespace-pre-wrap break-all rounded-md bg-soft p-2.5 font-mono text-caption leading-relaxed text-fg">{report.preview || '（无内容）'}</pre>
          {report.entries.length > 0 && (
            <div className="rounded-md border border-border p-2.5 text-caption">
              <b className="block">报告条目</b>
              <ul className="mt-1.5 grid gap-1 text-muted">
                {report.entries.map((e) => (
                  <li key={e.finding_id}>[{e.type}] {e.name} · {e.action}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {task.result?.changes && task.result.changes.length > 0 && (
        <div className="mt-3 rounded-md border border-border p-2.5 text-caption">
          <b className="block">更新页面</b>
          <ul className="mt-1.5 grid gap-1">
            {task.result.changes.map((path) => (
              <li key={path}>
                <button type="button" className="motion-interactive text-fg hover:underline" onClick={() => openWikiDoc(path)}>
                  {path}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {task.result?.conflicts && task.result.conflicts.length > 0 && (
        <div className="mt-3 rounded-md border border-warn bg-warn-soft p-2.5 text-caption">
          <b className="block">冲突</b>
          <ul className="mt-1.5 grid gap-1">
            {task.result.conflicts.map((c, i) => (
              <li key={i}>{c.note}{c.between?.length ? `（${c.between.join('、')}）` : ''}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4"><Button variant="compact" size="sm" onClick={onClose}>关闭</Button></div>
    </SectionCard>
  )
}

export function TasksPage() {
  const { rows, load, error } = useTasks()
  const { requestOpenSession } = useApp()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const queue = [...rows].sort((a, b) => (a.status !== 'done' && b.status === 'done' ? -1 : b.status !== 'done' && a.status === 'done' ? 1 : new Date(b.created_at).getTime() - new Date(a.created_at).getTime()))
  const selected = selectedId != null ? rows.find((t) => t.id === selectedId) ?? null : null

  return (
    <PageShell title="任务" description="后台维护任务状态一览：仅展示处理中 / 成功 / 失败，不提供重试、取消或编辑。">
      <div className="flex items-center justify-between gap-3">
        {error && <span className="text-caption text-warn">获取任务失败，显示最近一次数据。</span>}
        <div className="flex flex-wrap gap-2">
          <span className="rounded-pill bg-soft px-2.5 py-chip font-mono text-meta text-muted">共 {rows.length}</span>
          <span className="rounded-pill bg-soft px-2.5 py-chip font-mono text-meta text-muted">处理中 {rows.filter((t) => toState(t.status) === 'processing').length}</span>
          <span className="rounded-pill bg-soft px-2.5 py-chip font-mono text-meta text-muted">成功 {rows.filter((t) => toState(t.status) === 'done').length}</span>
          <span className="rounded-pill bg-soft px-2.5 py-chip font-mono text-meta text-muted">失败 {rows.filter((t) => toState(t.status) === 'failed').length}</span>
        </div>
        <Button variant="link" size="sm" className="h-auto p-0 text-caption" onClick={() => void load()}>刷新</Button>
      </div>

      <div className="mt-section-lg grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-content max-[820px]:grid-cols-1">
        <SectionCard className="overflow-hidden" contentClassName="p-0">
          <div className="border-b border-border px-cell py-[15px]"><h2 className="text-panel font-semibold">任务队列</h2></div>
          {queue.length === 0 ? (
            <EmptyState title="暂无任务" description="一切正常。" />
          ) : (
            <ul>
              {queue.map((t) => {
                const s = toState(t.status)
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(t.id)}
                      className={cn('flex w-full items-center gap-3 border-b border-border px-cell py-3 text-left transition-colors hover:bg-soft last:border-b-0', selected?.id === t.id && 'bg-soft')}
                    >
                      <span className={cn('h-2.5 w-2.5 shrink-0 rounded-pill', s === 'processing' ? 'animate-breathe bg-accent' : s === 'done' ? 'bg-ok' : 'bg-danger')} />
                      <span className="min-w-0 flex-1 truncate text-caption font-semibold">{t.original_name || `来源 #${t.source_id}`}</span>
                      <Badge variant={STATE_META[s].variant}>{STATE_META[s].label}</Badge>
                      <span className="whitespace-nowrap font-mono text-meta text-muted">{fmtTime(t.created_at)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </SectionCard>
        {selected ? (
          <TaskDetail
            task={selected}
            onBack={(sid) => requestOpenSession(sid)}
            onClose={() => setSelectedId(null)}
          />
        ) : (
          <SectionCard title="任务详情"><p className="mt-2.5 text-caption text-muted">选择左侧任务查看报告快照与失败原因。</p></SectionCard>
        )}
      </div>
    </PageShell>
  )
}
