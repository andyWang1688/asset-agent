import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { ReportSnapshot, TaskRow } from '@/lib/types'

/** 维护会话的只读聚合：报告快照 + 任务状态（均归属当前维护 session）。
 *  load 始终读取当前 session（ref），过期响应丢弃；切换会话先清空旧数据；
 *  活动任务每 2.5s 真实轮询；失败保留最后数据。 */
export function useMaintenance(sessionId: string | null) {
  const [reports, setReports] = useState<ReportSnapshot[]>([])
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const sessionRef = useRef(sessionId)
  sessionRef.current = sessionId

  const load = useCallback(async () => {
    const sid = sessionRef.current
    if (!sid) {
      setReports([])
      setTasks([])
      setError(false)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [reps, ts] = await Promise.all([api.reports(sid), api.tasks()])
      if (sessionRef.current !== sid) return // 会话已切换，丢弃过期响应
      setReports(reps)
      setTasks(ts.filter((t) => t.session_id === sid))
      setError(false)
    } catch {
      if (sessionRef.current === sid) setError(true) // 保留最后数据，不把失败当空库
    } finally {
      if (sessionRef.current === sid) setLoading(false)
    }
  }, [])

  useEffect(() => {
    setError(false)
    setReports([]) // 切换会话立即清掉旧会话数据，新数据到达前不残留
    setTasks([])
    void load()
  }, [sessionId, load])

  // 有非终态任务时轮询（真实拉取，不模拟进度）；无活动任务或卸载即清理
  const hasActive = tasks.some((t) => t.status !== 'done' && t.status !== 'failed')
    || reports.some((r) => r.status === 'pending' && (r.plan_status === 'queued' || r.plan_status === 'generating'))
  useEffect(() => {
    if (!sessionId || !hasActive) return
    const timer = setInterval(() => { void load() }, 2500)
    return () => clearInterval(timer)
  }, [sessionId, hasActive, load])

  return { reports, tasks, loading, error, load }
}
