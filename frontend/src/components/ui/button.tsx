import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * 全站唯一按钮组件：所有交互按钮必须走这里，禁止页面内手写按钮样式。
 * 视觉规则：1px 边框（只有颜色深浅两档）、圆角 token、150ms 过渡。
 */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-caption font-medium transition-[background,color,border-color,opacity,transform] duration-150 select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45 active:scale-[0.97] [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-fg text-surface hover:bg-fg/85',
        outline: 'border border-border bg-surface text-fg hover:border-border-strong hover:bg-soft',
        ghost: 'text-muted hover:bg-soft hover:text-fg',
        compact: 'border border-border bg-surface text-fg hover:border-border-strong',
        danger: 'border border-danger/25 bg-danger-soft text-danger hover:bg-danger-soft/70',
        link: 'text-fg underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-8 px-3.5',
        sm: 'h-7 rounded-sm px-2.5 text-meta',
        lg: 'h-9 px-4 text-body',
        icon: 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'outline',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  },
)
Button.displayName = 'Button'

export { Button, buttonVariants }
