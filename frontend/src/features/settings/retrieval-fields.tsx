import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { ModelDownloadStatus } from '@/lib/types'


/** 本地 sentence-transformers 路线的模型下载面板（进度轮询结果展示） */
export function DownloadPanel({ downloading, dlStatus, canDownload, onStart }: {
  downloading: boolean
  dlStatus: ModelDownloadStatus | null
  canDownload: boolean
  onStart: () => void
}) {
  const busy = dlStatus?.status === 'queued' || dlStatus?.status === 'downloading'
  return (
    <div className="flex w-full flex-col items-end gap-1.5 sm:w-64">
      <div className="flex select-none items-center gap-2">
        <Button size="sm" variant="outline" disabled={downloading || !canDownload} onClick={onStart}>
          {downloading ? '下载中…' : dlStatus?.downloaded ? '重新下载' : '下载模型'}
        </Button>
        {dlStatus?.downloaded && (
          <Badge variant="outline" className="text-emerald-600">
            已下载
          </Badge>
        )}
      </div>
      {busy && (
        <>
          <span className="font-mono text-xs text-muted-foreground">
            {dlStatus.status === 'queued' ? '排队中…' : `下载中 ${dlStatus.progress}%${dlStatus.files_total ? ` · ${dlStatus.files_done}/${dlStatus.files_total} 文件` : ''}`}
          </span>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-emerald-600 transition-[width]" style={{ width: `${dlStatus.progress}%` }} />
          </div>
        </>
      )}
      {dlStatus?.status === 'failed' && <p className="text-xs text-destructive">{dlStatus.error}</p>}
    </div>
  )
}
