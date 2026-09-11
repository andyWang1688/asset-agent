import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cn } from '@/lib/utils'

/**
 * shadcn 官方 Table 结构（table/thead/tbody/tr/th/td/caption）。
 * class 已按本项目语义 token 重排（见 docs/frontend-design-language.md），不新增局部颜色与字号。
 */
function Table({ className, ...props }: React.ComponentProps<'table'>) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table data-slot="table" className={cn('w-full border-collapse text-left text-caption', className)} {...props} />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<'thead'>) {
  return <thead data-slot="table-header" className={cn('bg-bg text-meta text-muted [&_tr]:border-t-0', className)} {...props} />
}

function TableBody({ className, ...props }: React.ComponentProps<'tbody'>) {
  return <tbody data-slot="table-body" className={className} {...props} />
}

/** asChild=true 时把样式与 data-slot 合并到子元素（用于 motion.tr 行级动效） */
function TableRow({ asChild = false, className, ...props }: React.ComponentProps<'tr'> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'tr'
  return <Comp data-slot="table-row" className={cn('border-t border-border align-top', className)} {...props} />
}

function TableHead({ className, ...props }: React.ComponentProps<'th'>) {
  return <th data-slot="table-head" className={cn('px-3 py-2.5 text-left align-middle font-medium whitespace-nowrap', className)} {...props} />
}

function TableCell({ className, ...props }: React.ComponentProps<'td'>) {
  return <td data-slot="table-cell" className={cn('px-3 py-3 align-middle whitespace-nowrap', className)} {...props} />
}

function TableCaption({ className, ...props }: React.ComponentProps<'caption'>) {
  return <caption data-slot="table-caption" className={cn('mt-4 text-caption text-muted', className)} {...props} />
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption }
