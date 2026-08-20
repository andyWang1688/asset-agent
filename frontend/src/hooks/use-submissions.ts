import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { PendingSubmission, SubmissionView } from '@/lib/types'

/** 待确认提交队列 + 确认视图加载 */
export function useSubmissions() {
  const [waiting, setWaiting] = useState<PendingSubmission[]>([])
  const [view, setView] = useState<SubmissionView | null>(null)
  const [loadingView, setLoadingView] = useState(false)

  const load = useCallback(async () => {
    try {
      const rows = await api.pendingSubmissions()
      setWaiting(rows.filter((s) => s.status === 'waiting'))
    } catch {
      setWaiting([])
    }
  }, [])

  const openView = useCallback(async (id: number) => {
    setLoadingView(true)
    try {
      const v = await api.submissionView(id)
      setView(v)
    } finally {
      setLoadingView(false)
    }
  }, [])

  /** 直接打开视图（/api/ingest 的待确认响应本身就是完整视图） */
  const setViewDirect = useCallback((v: SubmissionView) => setView(v), [])

  const closeView = useCallback(() => setView(null), [])

  useEffect(() => {
    void load()
  }, [load])

  return { waiting, view, loadingView, load, openView, setViewDirect, closeView }
}

/** 任务轮询（收集资料提交后跟踪整理进度） */
export function useTaskWatch() {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const [current, setCurrent] = useState<number | null>(null)

  const stop = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current)
      timer.current = null
    }
    setCurrent(null)
  }, [])

  const watch = useCallback((taskId: number, onUpdate: (t: { status: string; error: string | null; source_id: number; id: number }) => void) => {
    stop()
    setCurrent(taskId)
    const poll = async () => {
      try {
        const rows = await api.tasks()
        const t = rows.find((x) => x.id === taskId)
        if (t) {
          onUpdate({ status: t.status, error: t.error, source_id: t.source_id, id: t.id })
          if (t.status === 'done' || t.status === 'failed') stop()
        }
      } catch {
        /* 轮询失败不中断 */
      }
    }
    void poll()
    timer.current = setInterval(poll, 2500)
  }, [stop])

  useEffect(() => stop, [stop])

  return { watch, stop, current }
}
