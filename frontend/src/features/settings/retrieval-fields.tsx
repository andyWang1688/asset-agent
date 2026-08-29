import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { springTransition } from '@/components/layout'
import type { ModelDownloadStatus } from '@/lib/types'


/** 本地 sentence-transformers 路线的模型下载面板（进度轮询结果展示） */
export function DownloadPanel({ downloading, dlStatus, canDownload, onStart }: {
  downloading: boolean
  dlStatus: ModelDownloadStatus | null
  canDownload: boolean
  onStart: () => void
}) {
  const reduceMotion = useReducedMotion()
  return (
    <AnimatePresence initial={false}>
    <motion.div className="space-y-1.5 overflow-hidden pt-1" initial={reduceMotion ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reduceMotion ? undefined : { height: 0, opacity: 0 }} transition={springTransition(reduceMotion)}>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="compact" size="sm" disabled={downloading || !canDownload} onClick={onStart}>
          {downloading ? '下载中…' : dlStatus?.downloaded ? '重新下载' : '下载模型'}
        </Button>
        {dlStatus?.downloaded && <Badge variant="accent">已下载</Badge>}
        {dlStatus && (dlStatus.status === 'queued' || dlStatus.status === 'downloading') && (
          <span className="font-mono text-meta text-muted">
            {dlStatus.status === 'queued' ? '排队中…' : `下载中 ${dlStatus.progress}%${dlStatus.files_total ? ` · ${dlStatus.files_done}/${dlStatus.files_total} 文件` : ''}`}
          </span>
        )}
      </div>
      {dlStatus && (dlStatus.status === 'queued' || dlStatus.status === 'downloading') && (
        <div className="h-1.5 w-full overflow-hidden rounded-pill bg-border">
          <div className="motion-state h-full bg-accent transition-[width]" style={{ width: `${dlStatus.progress}%` }} />
        </div>
      )}
      {dlStatus?.status === 'failed' && <p className="text-caption text-danger">{dlStatus.error}</p>}
    </motion.div>
    </AnimatePresence>
  )
}
