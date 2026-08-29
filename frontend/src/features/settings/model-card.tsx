import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { staggerTransition } from '@/components/layout'
import type { ModelRow } from '@/lib/types'

export type ModelCardActions = {
  onAdd: () => void
  onActivate: (id: number) => void
  onTest: (id: number) => Promise<unknown>
  onEdit: (model: ModelRow) => void
  onDelete: (model: ModelRow) => void
}

/** 模型卡片：展示 + 连通测试微状态；增删改激活等副作用由页面经 ModelCardActions 注入 */
export function ModelCard({
  m,
  emptyDesc,
  emptyChip = '未激活',
  onAdd,
  onActivate,
  onTest,
  onEdit,
  onDelete,
  index = 0,
}: {
  m: ModelRow | null
  emptyDesc: string
  emptyChip?: string
  index?: number
} & ModelCardActions) {
  const [testing, setTesting] = useState(false)
  const reduceMotion = useReducedMotion()
  return (
    <motion.div className="mb-2 last:mb-0" layout initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}>
    <div className="motion-card rounded-md border border-border bg-bg p-3">
      <strong className="text-caption font-semibold">{m ? m.name : '尚未配置'}</strong>
      <p className="mt-1 break-words font-mono text-meta text-muted">
        {m ? `${m.base_url || ''}${m.model ? ` · ${m.model}` : ''}` : emptyDesc}
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Badge variant={m?.is_active ? 'accent' : 'muted'}>{m ? (m.is_active ? '激活' : '未激活') : emptyChip}</Badge>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {m ? (
            <>
              {!m.is_active && (
                <Button variant="compact" size="sm" onClick={() => onActivate(m.id)}>
                  激活
                </Button>
              )}
              <Button
                variant="compact"
                size="sm"
                disabled={testing}
                onClick={() => {
                  setTesting(true)
                  void onTest(m.id).finally(() => setTesting(false))
                }}
              >
                {testing ? '测试中…' : '测试'}
              </Button>
              <Button variant="compact" size="sm" onClick={() => onEdit(m)}>
                编辑
              </Button>
              <Button variant="danger" size="sm" onClick={() => onDelete(m)}>
                删除
              </Button>
            </>
          ) : (
            <Button variant="compact" size="sm" onClick={onAdd}>
              添加模型
            </Button>
          )}
        </div>
      </div>
    </div>
    </motion.div>
  )
}
