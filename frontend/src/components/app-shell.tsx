import type { ReactNode } from 'react'
import { AppSidebar } from '@/components/app-sidebar'
import { PrivateRefCard } from '@/components/private-ref-card'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import type { useChat } from '@/hooks/use-chat'

/** 应用外壳：GPT 式单侧栏 + 顶栏 + 内容区；页面切换使用统一的淡入上浮动画。 */
export function AppShell({
  chat,
  title,
  pageKey,
  children,
}: {
  chat: ReturnType<typeof useChat>
  title: string
  pageKey: string
  children: ReactNode
}) {
  return (
    <SidebarProvider>
      <AppSidebar chat={chat} />
      <SidebarInset className="h-[calc(100svh-1rem)] overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-4" />
          <h1 className="truncate text-sm font-semibold">{title}</h1>
        </header>
        <div className="flex min-h-0 flex-1">
          <div
            key={pageKey}
            className="flex min-h-0 flex-1 animate-in fade-in slide-in-from-bottom-2 duration-[350ms] motion-reduce:animate-none"
          >
            {children}
          </div>
        </div>
      </SidebarInset>
      <PrivateRefCard />
    </SidebarProvider>
  )
}
