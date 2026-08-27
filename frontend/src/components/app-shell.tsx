import { useEffect, useState, type ReactNode } from 'react'
import { useApp, type Tab } from '@/store/app-state'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { AppSidebar, MobileBottomNav } from '@/components/app-sidebar'
import { HistoryPanel } from '@/components/history-panel'
import type { ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

const PAGE_NAMES: Record<Tab, string> = {
  chat: '对话',
  wiki: '知识库',
  tasks: '任务',
  settings: '设置',
}

/** 顶栏：面包屑 + 历史按钮（桌面/移动共用） */
function Topbar({ pageName, onOpenHistory }: { pageName: string; onOpenHistory: () => void }) {
  return (
    <header className="sticky top-0 z-30 flex h-[58px] items-center justify-between border-b border-border bg-bg/92 px-[30px] backdrop-blur-md max-[820px]:px-4 max-[480px]:px-3">
      <div className="text-caption text-muted">
        工作台 / <b className="font-semibold text-fg">{pageName}</b>
      </div>
      <button
        type="button"
        aria-label="对话历史"
        onClick={onOpenHistory}
        className="grid h-[34px] w-[34px] place-items-center rounded-md border border-border bg-surface text-muted transition-colors duration-150 hover:bg-soft hover:text-fg"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-[15px] w-[15px]">
          <path d="M4.5 5.5v4h4" />
          <path d="M5.2 9.5a7.5 7.5 0 1 1-1.2 4" />
          <path d="M12 8.5v4l2.6 1.6" />
        </svg>
      </button>
    </header>
  )
}

/** 应用外壳：218px 固定侧栏 + 顶栏 + 内容页；≤820px 隐藏侧栏改底部导航；历史面板打开时桌面端内容让位 */
export function AppShell({
  children,
  onOpenSession,
  onNewChat,
  onNavigate,
}: {
  children: ReactNode
  onOpenSession: (sessionId: string, messages: ChatMessage[], title?: string | null) => void
  onNewChat: () => void
  onNavigate: (t: Tab) => void
}) {
  const { tab } = useApp()
  const isMobile = useIsMobile(820)
  const [histOpen, setHistOpen] = useState(false)
  const pageName = PAGE_NAMES[tab]

  useEffect(() => {
    if (!histOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHistOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [histOpen])

  if (isMobile) {
    return (
      <div className="flex min-h-svh flex-col">
        <Topbar pageName={pageName} onOpenHistory={() => setHistOpen(true)} />
        <main className={cn('page', tab === 'settings' && 'page-settings')}>{children}</main>
        <MobileBottomNav onNavigate={onNavigate} />
        <HistoryPanel open={histOpen} onClose={() => setHistOpen(false)} onOpenSession={onOpenSession} onNewChat={onNewChat} />
      </div>
    )
  }

  return (
    <div
      className={cn(
        'grid min-h-svh grid-cols-[218px_minmax(0,1fr)] transition-[margin-right] duration-500 ease-out',
        histOpen && 'mr-[218px]',
      )}
    >
      <AppSidebar onNavigate={onNavigate} />
      <div className="min-w-0">
        <Topbar pageName={pageName} onOpenHistory={() => setHistOpen(true)} />
        <main className={cn('page', tab === 'settings' && 'page-settings')}>{children}</main>
      </div>
      <HistoryPanel open={histOpen} onClose={() => setHistOpen(false)} onOpenSession={onOpenSession} onNewChat={onNewChat} />
    </div>
  )
}
