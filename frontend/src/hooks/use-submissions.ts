import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { PendingSubmission, SubmissionView } from '@/lib/types'

/** 待确认提交队列 + 确认视图加载；仅当前维护会话可读，切换会话丢弃过期结果。 */
export function useSubmissions(sessionId: string | null) {
  const [waiting, setWaiting] = useState<PendingSubmission[]>([])
  const [view, setView] = useState<SubmissionView | null>(null)
  const [loadingView, setLoadingView] = useState(false)
  const sessionRef = useRef(sessionId)
  sessionRef.current = sessionId

  const load = useCallback(async () => {
    const sid = sessionRef.current
    if (!sid) {
      setWaiting([])
      return
    }
    try {
      const rows = await api.pendingSubmissions()
      if (sessionRef.current !== sid) return
      setWaiting(rows.filter((s) => s.status === 'waiting' && s.session_id === sid))
    } catch {
      if (sessionRef.current === sid) setWaiting([])
    }
  }, [])

  const openView = useCallback(async (id: number) => {
    const sid = sessionId
    if (!sid) return // 非维护会话不读取确认视图
    setLoadingView(true)
    try {
      const v = await api.submissionView(id)
      if (sessionRef.current !== sid) return // 已切走，不打开确认
      setView(v)
    } catch {
      /* 打开失败保持无视图 */
    } finally {
      if (sessionRef.current === sid) setLoadingView(false)
    }
  }, [sessionId])

  /** 直接打开视图（/api/ingest 的待确认响应本身就是完整视图）；仅当前维护会话 */
  const setViewDirect = useCallback((v: SubmissionView) => {
    if (sessionRef.current == null) return
    setView(v)
  }, [])

  const closeView = useCallback(() => setView(null), [])

  useEffect(() => {
    setView(null) // 会话切换立即清掉旧确认视图
    void load()
  }, [sessionId, load])

  return { waiting, view, loadingView, load, openView, setViewDirect, closeView }
}
