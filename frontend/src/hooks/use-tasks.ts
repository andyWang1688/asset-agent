import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { TaskRow } from '@/lib/types'

/** 后台整理任务（/api/tasks、/api/tasks/{id}/retry） */
export function useTasks() {
  const [rows, setRows] = useState<TaskRow[]>([])

  const load = useCallback(async () => {
    try {
      setRows(await api.tasks())
    } catch {
      setRows([])
    }
  }, [])

  const retry = useCallback(async (id: number) => {
    await api.retryTask(id)
    await load()
  }, [load])

  useEffect(() => {
    void load()
  }, [load])

  const attention = rows.filter((t) => t.status !== 'done')
  const done = rows.filter((t) => t.status === 'done')

  return { rows, attention, done, load, retry }
}
