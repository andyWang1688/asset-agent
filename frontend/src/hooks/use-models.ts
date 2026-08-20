import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { ModelBody, ModelRow, Preset, TestResult } from '@/lib/types'

/** 模型配置（/api/settings/presets、/api/settings/models 系列） */
export function useModels() {
  const [presets, setPresets] = useState<Preset[]>([])
  const [rows, setRows] = useState<ModelRow[]>([])

  const loadPresets = useCallback(async () => {
    try {
      setPresets(await api.presets())
    } catch {
      setPresets([])
    }
  }, [])

  const load = useCallback(async () => {
    try {
      setRows(await api.models())
    } catch {
      setRows([])
    }
  }, [])

  const save = useCallback(async (body: ModelBody) => {
    await api.saveModel(body)
    await load()
  }, [load])

  const activate = useCallback(async (id: number) => {
    await api.activateModel(id)
    await load()
  }, [load])

  const test = useCallback(async (id: number): Promise<TestResult> => {
    try {
      return await api.testModel(id)
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : '测试失败' }
    }
  }, [])

  const remove = useCallback(async (id: number) => {
    await api.deleteModel(id)
    await load()
  }, [load])

  useEffect(() => {
    void loadPresets()
    void load()
  }, [loadPresets, load])

  return {
    presets,
    rows,
    knowledge: rows.filter((m) => m.role === 'knowledge'),
    security: rows.filter((m) => m.role === 'security'),
    load,
    save,
    activate,
    test,
    remove,
  }
}
