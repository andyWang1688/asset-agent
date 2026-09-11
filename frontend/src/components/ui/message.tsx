import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * shadcn 官方 Message 系列（结构照抄：data-slot + align 语义），class 已按本项目语义 token 重排。
 * 说明：只保留本项目用到的部分（未用到的头像/底部动作变体暂不引入）。
 */
function MessageGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="message-group" className={cn('flex min-w-0 flex-col gap-2', className)} {...props} />
}

function Message({ className, align = 'start', ...props }: React.ComponentProps<'div'> & { align?: 'start' | 'end' }) {
  return (
    <div
      data-slot="message"
      data-align={align}
      className={cn('group/message relative flex w-full min-w-0 gap-2 text-caption data-[align=end]:flex-row-reverse', className)}
      {...props}
    />
  )
}

function MessageContent({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="message-content"
      className={cn('flex w-full min-w-0 flex-col gap-2.5 wrap-break-word group-data-[align=end]/message:*:data-slot:self-end', className)}
      {...props}
    />
  )
}

function MessageHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="message-header" className={cn('flex max-w-full min-w-0 items-center px-3 text-meta font-medium text-muted', className)} {...props} />
}

function MessageFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="message-footer"
      className={cn('flex max-w-full min-w-0 items-center px-3 text-meta font-medium text-muted group-data-[align=end]/message:justify-end', className)}
      {...props}
    />
  )
}

export { MessageGroup, Message, MessageContent, MessageHeader, MessageFooter }
