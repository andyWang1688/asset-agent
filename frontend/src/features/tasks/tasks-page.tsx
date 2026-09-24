import { Fragment, useEffect, useState } from 'react'
import { ArrowUpRight, CheckCircle2, ChevronRight, CircleAlert, CircleDashed, FileText, MessageSquare, RefreshCw } from 'lucide-react'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useTasks } from '@/hooks/use-tasks'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { api } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { TaskRow } from '@/lib/types'
import { useApp } from '@/store/app-state'

type TaskState = 'processing' | 'done' | 'failed'
type TaskFilter = 'all' | TaskState

/** 耗时 = updated_at - created_at；未结束或无差值显示 — */
function duration(task: TaskRow): string {
  if (toState(task.status) === 'processing') return '—'
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

const STAGE_LABEL: Record<string, string> = {
  planning_pending: '等待处理', planning: '生成维护计划', drafting: '编写 Wiki 页面',
  saving: '保存资料与敏感信息', pending: '等待维护', processing: '更新 Wiki',
  credential_pending: '等待保险柜保存', retry: '等待维护',
}

function TaskExpand({ task }: { task: TaskRow }) {
  const { requestOpenSession, openWikiDoc } = useApp()
  const state = toState(task.status)
  const changes = task.result?.changes ?? []
  const conflicts = task.result?.conflicts ?? []
  const [titles, setTitles] = useState<Map<string, string>>(new Map())
  const needsTitles = changes.length > 0 || conflicts.some((c) => c.between?.length)
  useEffect(() => {
    if (!needsTitles) return
    let active = true
    void api.wikiPages().then((pages) => {
      if (active) setTitles(new Map(pages.map((page) => [page.path, page.title])))
    }).catch(() => {
      if (active) setTitles(new Map())
    })
    return () => { active = false }
  }, [needsTitles, task.updated_at])

  const pageLink = (path: string) => (
    <Button key={path} variant="ghost" size="sm" title={path}
      className="h-auto min-h-8 w-full min-w-0 justify-start py-2"
      onClick={() => openWikiDoc(path)}>
      <FileText data-icon="inline-start" className="text-muted-foreground" />
      <span className="min-w-0 flex-1 text-left whitespace-normal break-words">
        {titles.get(path)?.trim() || path.split('/').pop()?.replace(/\.md$/i, '') || path}
      </span>
      <ArrowUpRight data-icon="inline-end" className="text-muted-foreground" />
    </Button>
  )

  return (
    <section aria-label="任务详情" className="flex flex-col gap-5 bg-muted/30 px-4 py-5 sm:px-6">
      {state === 'processing' && <p aria-label="当前阶段" className="text-sm text-muted-foreground">{STAGE_LABEL[task.status] ?? '正在维护…'}</p>}
      {(task.error || state === 'failed') && (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertTitle>失败原因</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap break-words">{task.error || '本次维护未完成。'}</AlertDescription>
        </Alert>
      )}
      {(changes.length > 0 || conflicts.length > 0) && (
        <div className={cn('grid gap-6', changes.length > 0 && conflicts.length > 0 && 'lg:grid-cols-2')}>
          {changes.length > 0 && (
            <section aria-label="更新页面" className="flex min-w-0 flex-col gap-2">
              <h4 className="text-sm font-medium">更新页面 <span className="ml-1 text-xs text-muted-foreground">{changes.length}</span></h4>
              <ul className="flex flex-col gap-1">{changes.map((path) => <li key={path} className="min-w-0">{pageLink(path)}</li>)}</ul>
            </section>
          )}
          {conflicts.length > 0 && (
            <section aria-label="待核对事项" className="flex min-w-0 flex-col gap-2">
              <h4 className="flex items-center gap-2 text-sm font-medium"><CircleAlert className="size-4 text-amber-600" />待核对事项 <span className="text-xs text-muted-foreground">{conflicts.length}</span></h4>
              <ul className="flex flex-col divide-y">
                {conflicts.map((c, i) => (
                  <li key={i} className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">{c.note || '请核对相关页面中的信息。'}</p>
                    {c.between?.map(pageLink)}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
      {state === 'done' && changes.length === 0 && <p className="text-sm text-muted-foreground">本次未更新 Wiki 页面。</p>}
      <Separator />
      <footer className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span title={task.created_at}>开始 {fmtTime(task.created_at)}</span>
          <span title={task.updated_at}>{state === 'processing' ? '最近更新' : '结束'} {fmtTime(task.updated_at)}</span>
          {state !== 'processing' && <span>耗时 {duration(task)}</span>}
        </div>
        {task.session_id && <Button variant="outline" size="sm" onClick={() => requestOpenSession(task.session_id!)}><MessageSquare data-icon="inline-start" />回到原会话</Button>}
      </footer>
    </section>
  )
}

export function TasksPage() {
  const { rows, load, error } = useTasks()
  const compact = useIsMobile(767)
  const hideResult = useIsMobile(1023)
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
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">状态</TableHead>
                <TableHead>来源</TableHead>
                <TableHead className="hidden w-36 md:table-cell">时间</TableHead>
                <TableHead className="hidden w-20 text-right md:table-cell">耗时</TableHead>
                <TableHead className="hidden w-64 lg:table-cell">结果</TableHead>
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
                        <Button variant="ghost" size="sm" aria-label={`${open ? '收起' : '展开'}任务详情：${t.original_name || '知识库维护'}`}
                          aria-expanded={open} aria-controls={`task-details-${t.id}`}
                          onClick={(e) => { e.stopPropagation(); setExpanded(open ? null : t.id) }}>
                          <ChevronRight data-icon="inline-start" className={cn('transition-transform duration-300', open && 'rotate-90')} />
                          <TaskStatus state={state} />
                        </Button>
                      </TableCell>
                      <TableCell className="max-w-64 truncate text-sm" title={t.original_name || undefined}>{t.original_name || `来源 #${t.source_id}`}</TableCell>
                      <TableCell className="hidden font-mono text-xs text-muted-foreground md:table-cell">{fmtTime(t.created_at)}</TableCell>
                      <TableCell className="hidden text-right font-mono text-xs text-muted-foreground md:table-cell">{duration(t)}</TableCell>
                      <TableCell className="hidden truncate text-sm lg:table-cell">
                        {state === 'failed' ? (
                          <span className="text-destructive">{t.error?.split('\n')[0]}</span>
                        ) : state === 'processing' ? (
                          <span className="text-muted-foreground">{STAGE_LABEL[t.status] ?? '正在维护…'}</span>
                        ) : (
                          <span className="text-muted-foreground">更新 {changes.length} 页</span>
                        )}
                      </TableCell>
                    </TableRow>
                    <TableRow className="border-0 hover:bg-transparent">
                      <TableCell colSpan={compact ? 2 : hideResult ? 4 : 5} className="p-0">
                        <Collapsible open={open}>
                          <CollapsibleContent id={`task-details-${t.id}`} className="overflow-hidden [animation-duration:300ms] data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
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
