import * as React from 'react'
import { cn } from '@/lib/utils'

const INPUT_BASE =
  'w-full rounded-md border border-border bg-surface text-body transition-[border-color,box-shadow] duration-150 placeholder:text-muted/80 focus-visible:outline-none focus-visible:border-fg/45 focus-visible:ring-[3px] focus-visible:ring-soft disabled:cursor-not-allowed disabled:opacity-50'

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input type={type} className={cn(INPUT_BASE, 'h-8 px-3 py-1', className)} ref={ref} {...props} />
  ),
)
Input.displayName = 'Input'

export { Input }
