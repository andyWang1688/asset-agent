import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState, TableSkeleton, staggerTransition } from '@/components/layout'
import { api, errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { SecurityEvent } from '@/lib/types'

/** Safety events list: polls every 5 seconds while mounted (only mounted by the page when the events module is active) */
export function SecurityEventsSection() {
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [eventsClearing, setEventsClearing] = useState(false)
  const [eventPage, setEventPage] = useState(1)
  const reduceMotion = useReducedMotion()

  const loadEvents = useCallback(async () => {
    setEventsLoading(true)
    try {
      setEvents(await api.securityEvents())
    } catch {
      setEvents([])
    } finally {
      setEventsLoading(false)
    }
  }, [])

  useEffect(() => {
    setEventPage(1)
    void loadEvents()
    const timer = window.setInterval(() => void loadEvents(), 5000)
    return () => window.clearInterval(timer)
  }, [loadEvents])

            const pageSize = 20
            const pageCount = Math.max(1, Math.ceil(events.length / pageSize))
            const currentPage = Math.min(eventPage, pageCount)
            const pageEvents = events.slice((currentPage - 1) * pageSize, currentPage * pageSize)
            return <section>
              <div className="flex items-center justify-between border-b border-border px-cell py-3">
                <span className="text-meta text-muted">共 {events.length} 条</span>
                <div className="flex items-center gap-compact">
                  {events.length > 0 && <Button variant="danger" size="sm" onClick={() => void api.clearSecurityEvents().then(() => { setEventsClearing(true); setEvents([]); toast.success('安全事件已清空') }).catch((e) => toast.error(errMsg(e)))}>清空</Button>}
                  <Button
                    variant="compact"
                    size="icon"
                    onClick={() => void loadEvents()}
                    disabled={eventsLoading}
                    aria-label="刷新安全事件"
                    title="刷新"
                  >
                    <RefreshCw className={cn('h-4 w-4', eventsLoading && 'animate-spin')} />
                  </Button>
                </div>
              </div>
              {eventsLoading && events.length === 0 ? (
                <TableSkeleton rows={6} cols={3} />
              ) : events.length === 0 && !eventsClearing ? (
                <EmptyState title="暂无安全事件" />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[170px]">时间</TableHead>
                      <TableHead className="w-[150px]">类型</TableHead>
                      <TableHead>详情</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody><AnimatePresence initial={false} onExitComplete={() => setEventsClearing(false)}>
                    {pageEvents.map((event, index) => (
                      <TableRow asChild key={event.id}>
                        <motion.tr initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}>
                          <TableCell className="font-mono text-meta text-muted"><time dateTime={event.created_at}>{fmtTime(event.created_at)}</time></TableCell>
                          <TableCell><Badge variant="muted">{event.kind}</Badge></TableCell>
                          <TableCell className="whitespace-normal break-words text-fg">{event.detail}</TableCell>
                        </motion.tr>
                      </TableRow>
                    ))}
                  </AnimatePresence></TableBody>
                </Table>
              )}
              {events.length > 0 && <div className="flex items-center justify-between border-t border-border px-cell py-3">
                <span className="text-meta text-muted">第 {currentPage} / {pageCount} 页</span>
                <div className="flex items-center gap-1.5">
                  <Button variant="compact" size="icon" onClick={() => setEventPage((page) => Math.max(1, page - 1))} disabled={currentPage === 1} aria-label="上一页"><ChevronLeft /></Button>
                  <Button variant="compact" size="icon" onClick={() => setEventPage((page) => Math.min(pageCount, page + 1))} disabled={currentPage === pageCount} aria-label="下一页"><ChevronRight /></Button>
                </div>
              </div>}
            </section>
}
