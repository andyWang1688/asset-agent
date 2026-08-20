import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * 全站唯一面板组件：1px 边框 + 统一圆角/阴影。
 * 列表行分隔统一用 Row 组件（border-b border-border）。
 */
function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-lg border border-border bg-surface shadow-panel', className)}
      {...props}
    />
  )
}

/** 面板头：标题 + 右侧动作区 */
function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center justify-between gap-3 border-b border-border px-4 py-3.5', className)} {...props} />
}

/** 面板标题 */
function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-panel font-semibold', className)} {...props} />
}

function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 py-3.5', className)} {...props} />
}

/** 列表行：统一 1px 下边框与内边距 */
function Row({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('border-b border-border last:border-b-0', className)} {...props} />
}

/** 空态占位 */
function Empty({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('px-4 py-6 text-center text-caption text-muted', className)} {...props} />
}

export { Card, CardHeader, CardTitle, CardBody, Row, Empty }
