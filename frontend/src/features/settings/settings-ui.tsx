import type { ReactNode } from 'react'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/** 设置页分组卡：官方 Card 形态，组头承载标题/徽标/操作，内容按行排列 */
export function SettingsGroup({
  title,
  description,
  badge,
  action,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  badge?: ReactNode
  action?: ReactNode
  children?: ReactNode
}) {
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <CardHeader className="border-b px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-sm">{title}</CardTitle>
          {badge}
          {action && <div className="ml-auto">{action}</div>}
        </div>
        {description && <CardDescription className="text-xs leading-relaxed">{description}</CardDescription>}
      </CardHeader>
      {children}
    </Card>
  )
}

/** 设置页分组行：左侧标签与说明，右侧控件 */
export function SettingsRow({
  label,
  description,
  control,
}: {
  label: ReactNode
  description?: ReactNode
  control?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b px-4 py-3 last:border-b-0">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">{control}</div>
    </div>
  )
}
