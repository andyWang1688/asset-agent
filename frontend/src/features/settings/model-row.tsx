import { useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ModelRow as ModelRowData } from '@/lib/types'
import { SettingsRow } from './settings-ui'

export type ModelRowActions = {
  onAdd: () => void
  onActivate: (id: number) => void
  onTest: (id: number) => Promise<unknown>
  onEdit: (model: ModelRowData) => void
  onDelete: (model: ModelRowData) => void
}

/** 模型行：名称与激活状态 + 地址说明；操作由页面注入 */
export function ModelRow({
  m,
  onActivate,
  onTest,
  onEdit,
  onDelete,
}: {
  m: ModelRowData
} & ModelRowActions) {
  const [testing, setTesting] = useState(false)
  return (
    <SettingsRow
      label={
        <span className="flex items-center gap-2">
          {m.name}
          {m.is_active ? (
            <span className="inline-flex items-center gap-1 text-xs font-normal text-emerald-600">
              <CheckCircle2 className="size-3.5" />
              已激活
            </span>
          ) : (
            <span className="text-xs font-normal text-muted-foreground">未激活</span>
          )}
        </span>
      }
      description={[m.base_url, m.model].filter(Boolean).join(' · ')}
      control={
        <>
          {!m.is_active && (
            <Button size="sm" variant="outline" onClick={() => onActivate(m.id)}>
              激活
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={testing}
            onClick={() => {
              setTesting(true)
              void onTest(m.id).finally(() => setTesting(false))
            }}
          >
            {testing ? '测试中…' : '测试'}
          </Button>
          <Button size="sm" variant="outline" onClick={() => onEdit(m)}>
            编辑
          </Button>
          <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => onDelete(m)}>
            删除
          </Button>
        </>
      }
    />
  )
}
