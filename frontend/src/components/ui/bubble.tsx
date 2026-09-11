import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

/**
 * shadcn 官方 Bubble（结构照抄），配色改用本项目语义 token：
 * default = 用户气泡（深底浅字）、muted = 回答气泡（柔底）、ghost = 无气泡。
 */
function BubbleGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="bubble-group" className={cn('flex min-w-0 flex-col gap-2', className)} {...props} />
}

const bubbleVariants = cva(
  'group/bubble relative flex w-fit max-w-[88%] min-w-0 flex-col gap-1 group-data-[align=end]/message:self-end data-[align=end]:self-end data-[variant=ghost]:max-w-full',
  {
    variants: {
      variant: {
        default: '*:data-[slot=bubble-content]:bg-fg *:data-[slot=bubble-content]:text-surface',
        muted: '*:data-[slot=bubble-content]:bg-soft *:data-[slot=bubble-content]:text-fg',
        ghost: '*:data-[slot=bubble-content]:bg-transparent *:data-[slot=bubble-content]:px-0 *:data-[slot=bubble-content]:py-0',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

function Bubble({
  variant = 'default',
  align = 'start',
  className,
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof bubbleVariants> & { align?: 'start' | 'end' }) {
  return <div data-slot="bubble" data-variant={variant} data-align={align} className={cn(bubbleVariants({ variant }), className)} {...props} />
}

function BubbleContent({
  asChild = false,
  className,
  ...props
}: React.ComponentProps<'div'> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'div'
  return (
    <Comp
      data-slot="bubble-content"
      className={cn(
        'w-fit max-w-full min-w-0 rounded-md px-3.5 py-2.5 text-caption leading-[1.6] wrap-break-word group-data-[align=end]/bubble:self-end',
        className,
      )}
      {...props}
    />
  )
}

export { BubbleGroup, Bubble, BubbleContent }
