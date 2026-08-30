import { useCallback, useState, type CSSProperties, type ReactNode } from 'react'
import type { Tab } from '@/store/app-state'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { AppSidebar } from '@/components/app-sidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { useSidebar } from '@/components/ui/sidebar-context'
import { readSidebarWidth } from '@/lib/sidebar-width'

/** 移动端标题栏：汉堡（一级菜单 Sheet）+ 品牌；历史属于聊天页，不在此出现 */
function MobileTopbar() {
  const { toggleSidebar } = useSidebar()
  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 bg-surface px-4 max-[480px]:px-3">
      <button
        type="button"
        aria-label="打开一级菜单"
        title="一级菜单"
        onClick={toggleSidebar}
        className="motion-interactive grid h-[30px] w-[30px] place-items-center rounded-md text-muted transition-[color,background-color,transform] hover:bg-soft hover:text-fg active:scale-[0.97]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-[15px] w-[15px]">
          <path d="M5 7h14M5 12h14M5 17h10" />
        </svg>
      </button>
      <div className="flex items-center gap-2 text-body font-bold">
        <span className="grid h-[26px] w-[26px] place-items-center rounded-sm bg-fg font-mono text-meta font-bold text-surface">
          AA
        </span>
        资产 Agent
      </div>
    </header>
  )
}

/** 应用外壳：只负责两栏布局、左栏一级菜单、桌面边界控制、移动端菜单入口；不拥有对话历史 */
export function AppShell({ children, onNavigate }: { children: ReactNode; onNavigate: (t: Tab) => void }) {
  const isMobile = useIsMobile(820)
  const [defaultOpen] = useState(() => document.cookie.split('; ').find((c) => c.startsWith('sidebar_state='))?.split('=')[1] !== 'false')
  const [sidebarWidth, setSidebarWidthState] = useState(() => readSidebarWidth(window.localStorage))
  const setSidebarWidth = useCallback((w: number) => {
    setSidebarWidthState(w)
    window.localStorage.setItem('sidebar-width', String(w))
  }, [])

  if (isMobile) {
    return (
      <SidebarProvider defaultOpen={defaultOpen} style={{ '--sidebar-width': `${sidebarWidth}px`, '--sidebar-width-icon': '4rem' } as CSSProperties}>
        <div className="flex h-svh min-h-0 w-full min-w-0 flex-col overflow-hidden">
          <MobileTopbar />
          <AppSidebar onNavigate={onNavigate} width={sidebarWidth} onWidthChange={setSidebarWidth} />
          <main className="min-h-0 flex-1 bg-surface p-3">
            <div className="app-main-scroll relative h-full overflow-y-auto overflow-x-hidden rounded-xl border border-border bg-surface shadow-panel">{children}</div>
          </main>
        </div>
      </SidebarProvider>
    )
  }

  return (
    <SidebarProvider defaultOpen={defaultOpen} style={{ '--sidebar-width': `${sidebarWidth}px`, '--sidebar-width-icon': '4rem' } as CSSProperties}>
      <div className="flex h-svh min-h-0 w-full min-w-0 flex-col overflow-hidden">
        <div className="flex min-h-0 flex-1">
          <AppSidebar onNavigate={onNavigate} width={sidebarWidth} onWidthChange={setSidebarWidth} />
          <main className="min-h-0 min-w-0 flex-1 bg-surface p-3">
            <div className="app-main-scroll relative h-full overflow-y-auto overflow-x-hidden rounded-xl border border-border bg-surface shadow-panel">{children}</div>
          </main>
        </div>
      </div>
    </SidebarProvider>
  )
}
