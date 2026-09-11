import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { TaskRow } from '@/lib/types'

/** 后台维护任务（/api/tasks）。1.0 只读：处理中/成功/失败，无重试/取消/删除/编辑。
 *  有非终态任务时真实轮询；失败保留最后数据。 */
export function useTasks() {
  const [rows, setRows] = useState<TaskRow[]>([])
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    try {
      setRows(await api.tasks())
      setError(false)
    } catch {
      setError(true)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const hasActive = rows.some((t) => t.status !== 'done' && t.status !== 'failed')
  useEffect(() => {
    if (!hasActive) return
    const timer = setInterval(() => { void load() }, 2500)
    return () => clearInterval(timer)
  }, [hasActive, load])

  const attention = rows.filter((t) => t.status !== 'done')
  const done = rows.filter((t) => t.status === 'done')

  return { rows, attention, done, load, error }
}
