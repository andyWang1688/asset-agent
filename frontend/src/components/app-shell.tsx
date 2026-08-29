import { useEffect, useState, type ReactNode } from 'react'
import type { Tab } from '@/store/app-state'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { AppSidebar, MobileBottomNav } from '@/components/app-sidebar'
import { HistoryPanel } from '@/components/history-panel'
import type { ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

/** 顶栏：折叠按钮 + 品牌 + 历史按钮（桌面/移动共用，New API 式全宽顶栏） */
function Topbar({ collapsed, onToggleSidebar, onOpenHistory }: { collapsed: boolean; onToggleSidebar: () => void; onOpenHistory: () => void }) {
  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center justify-between bg-surface px-[30px] max-[820px]:px-4 max-[480px]:px-3">
      <div className="flex items-center gap-2 text-body font-bold">
        <button
          type="button"
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
          onClick={onToggleSidebar}
          className={cn('motion-interactive grid h-[30px] w-[30px] place-items-center rounded-md transition-[color,background-color,transform] hover:bg-soft hover:text-fg active:scale-[0.97] max-[820px]:hidden', collapsed ? 'border border-border bg-soft text-fg' : 'text-muted')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-[15px] w-[15px]">
            <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
            <path d="M9.5 4.5v15" />
          </svg>
        </button>
        <span className="h-4 w-px bg-border max-[820px]:hidden" aria-hidden="true" />
        <span className="grid h-[26px] w-[26px] place-items-center rounded-sm bg-fg font-mono text-meta font-bold text-surface">
          AA
        </span>
        资产 Agent
      </div>
      <button
        type="button"
        aria-label="对话历史"
        onClick={onOpenHistory}
        className="motion-interactive grid h-[34px] w-[34px] place-items-center rounded-md border border-border bg-surface text-muted transition-[color,background-color,transform] hover:bg-soft hover:text-fg active:scale-[0.97]"
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
  const isMobile = useIsMobile(820)
  const [histOpen, setHistOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('sidebar-collapsed') === '1')
  const toggleSidebar = () =>
    setCollapsed((c) => {
      localStorage.setItem('sidebar-collapsed', c ? '0' : '1')
      return !c
    })
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
      <div className="flex h-svh min-h-0 flex-col overflow-hidden">
        <Topbar collapsed={collapsed} onToggleSidebar={toggleSidebar} onOpenHistory={() => setHistOpen(true)} />
        <main className="min-h-0 flex-1 bg-surface p-3">
          <div className="app-main-scroll h-full overflow-y-auto overflow-x-hidden rounded-xl border border-border bg-surface shadow-panel">{children}</div>
        </main>
        <MobileBottomNav onNavigate={onNavigate} />
        <HistoryPanel open={histOpen} onClose={() => setHistOpen(false)} onOpenSession={onOpenSession} onNewChat={onNewChat} />
      </div>
    )
  }

  return (
    <div className="flex h-svh min-h-0 flex-col overflow-hidden">
      <Topbar collapsed={collapsed} onToggleSidebar={toggleSidebar} onOpenHistory={() => setHistOpen(true)} />
      <div
        className={cn(
          'motion-spring flex min-h-0 flex-1 overflow-hidden transition-[margin-right]',
          histOpen && 'mr-[218px]',
        )}
      >
        <AppSidebar collapsed={collapsed} onNavigate={onNavigate} />
        <main className="min-h-0 min-w-0 flex-1 bg-surface p-4">
          <div className="app-main-scroll h-full overflow-y-auto overflow-x-hidden rounded-xl border border-border bg-surface shadow-panel">{children}</div>
        </main>
      </div>
      <HistoryPanel open={histOpen} onClose={() => setHistOpen(false)} onOpenSession={onOpenSession} onNewChat={onNewChat} />
    </div>
  )
}
