import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, RefreshCw, Siren } from 'lucide-react'
import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { SecurityEvent } from '@/lib/types'
import { SettingsGroup } from './settings-ui'

const PAGE_SIZE = 20

/** 安全事件：挂载期间每 5 秒轮询；分页、清空（二次确认）与手动刷新 */
export function SecurityEventsSection() {
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [confirmClear, setConfirmClear] = useState(false)

  const loadEvents = useCallback(async () => {
    setLoading(true)
    try {
      setEvents(await api.securityEvents())
    } catch {
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setPage(1)
    void loadEvents()
    const timer = window.setInterval(() => void loadEvents(), 5000)
    return () => window.clearInterval(timer)
  }, [loadEvents])

  const pageCount = Math.max(1, Math.ceil(events.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const pageEvents = events.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const clearAll = () => {
    void api
      .clearSecurityEvents()
      .then(() => {
        setEvents([])
        setPage(1)
        toast.success('安全事件已清空')
      })
      .catch((e) => toast.error(errMsg(e)))
      .finally(() => setConfirmClear(false))
  }

  return (
    <>
      <SettingsGroup
        title="安全事件"
        description="检测与处理记录，自动刷新。"
        action={
          <div className="flex items-center gap-2">
            {events.length > 0 && (
              <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setConfirmClear(true)}>
                清空
              </Button>
            )}
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => void loadEvents()}
              disabled={loading}
              aria-label="刷新安全事件"
              title="刷新"
            >
              <RefreshCw className={cn(loading && 'animate-spin')} />
            </Button>
          </div>
        }
      >
        {loading && events.length === 0 ? (
          <div className="space-y-3 p-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <Empty className="border-0 py-10">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Siren />
              </EmptyMedia>
              <EmptyTitle>暂无安全事件</EmptyTitle>
              <EmptyDescription>检测与处理记录会显示在这里，每 5 秒自动刷新。</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[170px]">时间</TableHead>
                <TableHead className="w-[150px]">类型</TableHead>
                <TableHead>详情</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageEvents.map((event) => (
                <TableRow key={event.id} className="animate-in fade-in">
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    <time dateTime={event.created_at}>{fmtTime(event.created_at)}</time>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{event.kind}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-normal break-words text-foreground">{event.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {events.length > 0 && (
          <div className="flex items-center justify-between border-t px-4 py-3">
            <span className="text-xs text-muted-foreground">
              共 {events.length} 条 · 第 {currentPage} / {pageCount} 页
            </span>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                disabled={currentPage === 1}
                aria-label="上一页"
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
                disabled={currentPage === pageCount}
                aria-label="下一页"
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        )}
      </SettingsGroup>

      <AlertDialog open={confirmClear} onOpenChange={setConfirmClear}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>清空安全事件？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除全部 {events.length} 条检测与处理记录，此操作不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={clearAll}>
              确认清空
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
