import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * 全站唯一徽标组件：pill 圆角 + 语义色，字号统一 text-meta。
 */
const badgeVariants = cva(
  'inline-flex items-center whitespace-nowrap rounded-pill px-2 py-0.5 text-meta font-medium leading-[1.6]',
  {
    variants: {
      variant: {
        accent: 'bg-accent-soft text-accent-strong',
        muted: 'bg-soft text-muted',
        ok: 'bg-ok-soft text-ok',
        warn: 'bg-warn-soft text-warn',
        err: 'bg-danger-soft text-danger',
      },
    },
    defaultVariants: { variant: 'muted' },
  },
)

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge }
