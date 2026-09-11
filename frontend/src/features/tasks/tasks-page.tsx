import { Fragment, useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, CircleDashed, RefreshCw } from 'lucide-react'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useTasks } from '@/hooks/use-tasks'
import { api } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ReportSnapshot, TaskRow } from '@/lib/types'
import { useApp } from '@/store/app-state'

type TaskState = 'processing' | 'done' | 'failed'
type TaskFilter = 'all' | TaskState

/** 耗时 = updated_at - created_at；未结束或无差值显示 — */
function duration(task: TaskRow): string {
  const t = (s: string) => new Date(s.replace(' ', 'T')).getTime()
  const ms = t(task.updated_at) - t(task.created_at)
  if (!Number.isFinite(ms) || ms <= 0) return '—'
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${Math.max(sec, 1)}s`
  const min = Math.round(sec / 60)
  return min < 60 ? `${min}m` : `${Math.round(min / 60)}h`
}

function toState(status: string): TaskState {
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  return 'processing' // pending / processing / credential_pending / retry
}

const STATE_META: Record<TaskState, { label: string; icon: typeof CheckCircle2; className: string }> = {
  processing: { label: '处理中', icon: CircleDashed, className: 'text-muted-foreground' },
  done: { label: '成功', icon: CheckCircle2, className: 'text-emerald-600' },
  failed: { label: '失败', icon: CircleAlert, className: 'text-destructive' },
}

function TaskStatus({ state }: { state: TaskState }) {
  const meta = STATE_META[state]
  const Icon = meta.icon
  return (
    <span className="flex items-center gap-1.5">
      <Icon
        className={cn(
          'size-3.5 shrink-0',
          meta.className,
          state === 'processing' && 'animate-spin [animation-duration:3s]',
        )}
      />
      <span className="text-sm">{meta.label}</span>
    </span>
  )
}

const REPORT_STATUS: Record<ReportSnapshot['status'], string> = {
  pending: '待确认',
  confirmed: '已确认',
  auto: '自动处理',
  rejected: '已拒绝',
}

function ReportPanel({ reportId }: { reportId: number }) {
  const [report, setReport] = useState<ReportSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void api
      .reportView(reportId)
      .then((r) => { if (!cancelled) setReport(r) })
      .catch(() => { if (!cancelled) setReport(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [reportId])

  if (loading) return <Skeleton className="mt-3 h-24 w-full" />
  if (!report) return null
  return (
    <div className="mt-3 grid gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={report.status === 'rejected' ? 'destructive' : 'secondary'}
          className={report.status === 'pending' ? 'text-amber-600' : undefined}
        >
          {REPORT_STATUS[report.status]}
        </Badge>
        <span className="text-xs text-muted-foreground">{report.original_name || '手动输入'}</span>
      </div>
      <pre className="max-h-[260px] overflow-y-auto whitespace-pre-wrap break-all rounded-md bg-muted p-2.5 font-mono text-xs leading-relaxed">
        {report.preview || '（无内容）'}
      </pre>
      {report.entries.length > 0 && (
        <div className="rounded-md border p-2.5 text-xs">
          <p className="font-medium">报告条目</p>
          <ul className="mt-1.5 grid gap-1 text-muted-foreground">
            {report.entries.map((e) => (
              <li key={e.finding_id}>[{e.type}] {e.name} · {e.action}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function TaskExpand({ task }: { task: TaskRow }) {
  const { requestOpenSession, openWikiDoc } = useApp()
  const state = toState(task.status)
  const changes = task.result?.changes ?? []
  const conflicts = task.result?.conflicts ?? []
  return (
    <div className="border-t bg-muted/30 px-4 py-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted-foreground">来源会话</p>
          <p className="mt-1 truncate font-mono text-sm">{task.session_id || '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">任务</p>
          <p className="mt-1 font-mono text-sm">#{task.id}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">状态</p>
          <p className="mt-1 text-sm">{STATE_META[state].label}</p>
        </div>
      </div>
      {task.error && (
        <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm whitespace-pre-wrap text-destructive">
          {task.error}
        </div>
      )}
      {state === 'processing' && (
        <p className="mt-3 text-sm text-muted-foreground">
          编译进行中，完成后这里会列出更新的页面。任务锁定，不能取消或重试。
        </p>
      )}
      {changes.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-muted-foreground">更新页面</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {changes.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => openWikiDoc(c)}
                className="rounded-md border bg-background px-2 py-1 font-mono text-xs transition-colors hover:bg-muted"
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      )}
      {conflicts.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-600/30 bg-amber-600/5 p-3 text-sm text-amber-600">
          <p className="text-xs font-medium">冲突</p>
          <ul className="mt-1.5 grid gap-1">
            {conflicts.map((c, i) => (
              <li key={i}>{c.note}{c.between?.length ? `（${c.between.join('、')}）` : ''}</li>
            ))}
          </ul>
        </div>
      )}
      {task.session_id && (
        <Button variant="outline" size="sm" className="mt-3" onClick={() => requestOpenSession(task.session_id!)}>
          回到原会话
        </Button>
      )}
      {task.report_id != null && <ReportPanel reportId={task.report_id} />}
    </div>
  )
}

export function TasksPage() {
  const { rows, load, error } = useTasks()
  const [filter, setFilter] = useState<TaskFilter>('all')
  const [q, setQ] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const counts = rows.reduce(
    (acc, t) => {
      acc.all += 1
      acc[toState(t.status)] += 1
      return acc
    },
    { all: 0, processing: 0, done: 0, failed: 0 } as Record<TaskFilter, number>,
  )

  const kw = q.trim().toLowerCase()
  const visible = [...rows]
    .sort((a, b) => {
      const ap = toState(a.status) === 'processing' ? 0 : 1
      const bp = toState(b.status) === 'processing' ? 0 : 1
      return ap - bp || new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
    .filter((t) => filter === 'all' || toState(t.status) === filter)
    .filter((t) => !kw || (t.original_name ?? '').toLowerCase().includes(kw) || String(t.source_id).includes(kw))

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5">
        <SegmentedTabs
          value={filter}
          onChange={setFilter}
          size="sm"
          options={[
            { value: 'all', label: `全部 ${counts.all}` },
            { value: 'processing', label: `处理中 ${counts.processing}` },
            { value: 'done', label: `成功 ${counts.done}` },
            { value: 'failed', label: `失败 ${counts.failed}` },
          ]}
        />
        {error && <span className="text-xs text-amber-600">获取任务失败，显示最近一次数据。</span>}
        <div className="ml-auto flex items-center gap-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索来源"
            className="w-full sm:w-56"
          />
          <Button variant="outline" size="icon-sm" aria-label="刷新任务" title="刷新" onClick={() => void load()}>
            <RefreshCw />
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>暂无任务</EmptyTitle>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-28">状态</TableHead>
                <TableHead>来源</TableHead>
                <TableHead className="w-36">时间</TableHead>
                <TableHead className="w-20 text-right">耗时</TableHead>
                <TableHead className="w-64">结果</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((t) => {
                const state = toState(t.status)
                const open = expanded === t.id
                const changes = t.result?.changes ?? []
                return (
                  <Fragment key={t.id}>
                    <TableRow
                      className="cursor-pointer"
                      data-state={open ? 'open' : 'closed'}
                      onClick={() => setExpanded(open ? null : t.id)}
                    >
                      <TableCell>
                        <TaskStatus state={state} />
                      </TableCell>
                      <TableCell className="max-w-64 truncate text-sm">{t.original_name || `来源 #${t.source_id}`}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{fmtTime(t.created_at)}</TableCell>
                      <TableCell className="text-right font-mono text-xs text-muted-foreground">{duration(t)}</TableCell>
                      <TableCell className="truncate text-sm">
                        {state === 'failed' ? (
                          <span className="text-destructive">{t.error?.split('\n')[0]}</span>
                        ) : state === 'processing' ? (
                          <span className="text-muted-foreground">正在编译 Wiki…</span>
                        ) : (
                          <span className="text-muted-foreground">更新 {changes.length} 页</span>
                        )}
                      </TableCell>
                    </TableRow>
                    <TableRow className="border-0 hover:bg-transparent">
                      <TableCell colSpan={5} className="p-0">
                        <Collapsible open={open}>
                          <CollapsibleContent className="overflow-hidden [animation-duration:300ms] data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
                            <TaskExpand task={t} />
                          </CollapsibleContent>
                        </Collapsible>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
