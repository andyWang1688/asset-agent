import * as React from 'react'
import { cn } from '@/lib/utils'

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      className={cn(
        'flex w-full rounded-md border border-border bg-surface px-3 py-2 text-body transition-[border-color,box-shadow] duration-150 placeholder:text-muted/80 focus-visible:outline-none focus-visible:border-fg/45 focus-visible:ring-[3px] focus-visible:ring-soft disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Textarea }
