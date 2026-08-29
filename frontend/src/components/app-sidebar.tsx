import type { ReactElement } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Bot, Search, ShieldCheck, Siren } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { NavHighlight, stateTransition } from '@/components/layout'
import { useTasks } from '@/hooks/use-tasks'
import { useApp, type SettingsRoute, type Tab } from '@/store/app-state'

const ICONS: Record<Tab, ReactElement> = {
  chat: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4 w-4 shrink-0">
      <path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4.6A2.5 2.5 0 0 1 5 12.5z" />
    </svg>
  ),
  wiki: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4 w-4 shrink-0">
      <path d="M4 5.5h6l2 2H20v11H4z" />
      <path d="M4 7.5h16" />
    </svg>
  ),
  tasks: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4 w-4 shrink-0">
      <path d="M5 6h14M5 12h14M5 18h9" />
      <path d="m17 17 2 2 3-4" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4 w-4 shrink-0">
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </svg>
  ),
}

type NavItemDef = { tab: Tab; label: string }

const NAV_WORKSPACE: NavItemDef[] = [
  { tab: 'chat', label: '对话' },
  { tab: 'wiki', label: '知识库' },
  { tab: 'tasks', label: '任务' },
]
const NAV_LOCAL: { route: SettingsRoute; label: string; icon: typeof Bot }[] = [
  { route: 'models', label: '模型配置', icon: Bot },
  { route: 'retrieval', label: '检索配置', icon: Search },
  { route: 'security', label: '安全策略', icon: ShieldCheck },
  { route: 'events', label: '安全事件', icon: Siren },
]

/** shadcn 官方 Sidebar（New API 同款）：collapsible=icon，滑动高亮保留 */
export function AppSidebar({ onNavigate }: { onNavigate?: (t: Tab) => void }) {
  const { attention } = useTasks()
  const { tab, setTab, navigateSettings, settingsRoute } = useApp()
  const reduceMotion = useReducedMotion()
  const activeRoute = tab === 'settings' ? settingsRoute : null
  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>工作区</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_WORKSPACE.map(({ tab: t, label }) => (
                <SidebarMenuItem key={t}>
                  <SidebarMenuButton
                    isActive={tab === t}
                    title={label}
                    onClick={() => {
                      setTab(t)
                      onNavigate?.(t)
                    }}
                    className="relative isolate data-[active=true]:bg-transparent"
                  >
                    {tab === t && (
                      <motion.span layoutId="primary-nav-highlight" className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent" transition={stateTransition(reduceMotion)} aria-hidden="true" />
                    )}
                    {ICONS[t]}
                    <span>{label}</span>
                    {t === 'tasks' && attention.length > 0 && (
                      <span className="ml-auto">
                        <Badge variant="muted" className="font-mono">{attention.length}</Badge>
                      </span>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>本地设置</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_LOCAL.map(({ route, label, icon: Icon }) => (
                <SidebarMenuItem key={route}>
                  <SidebarMenuButton
                    isActive={activeRoute === route}
                    title={label}
                    onClick={() => {
                      navigateSettings(route)
                      onNavigate?.('settings')
                    }}
                    className="relative isolate data-[active=true]:bg-transparent"
                  >
                    {activeRoute === route && (
                      <motion.span layoutId="primary-nav-highlight" className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent" transition={stateTransition(reduceMotion)} aria-hidden="true" />
                    )}
                    <Icon className="h-4 w-4 shrink-0" strokeWidth={1.7} />
                    <span>{label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}

/** 移动端底部导航（≤820px 显示） */
export function MobileBottomNav({ onNavigate }: { onNavigate?: (t: Tab) => void }) {
  const { tab, setTab, navigateSettings, settingsRoute } = useApp()
  const itemClass = (active: boolean) => (active ? 'flex-1 rounded-md font-semibold text-fg' : 'flex-1 rounded-md text-fg opacity-55')
  const contentClass = 'flex flex-col items-center gap-[3px] px-1 py-chip text-[10.5px]'
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-[70] flex border-t border-border px-2 pb-[calc(6px+env(safe-area-inset-bottom))] pt-1.5 backdrop-blur-md"
      style={{ background: 'color-mix(in oklch, var(--color-surface) 92%, transparent)' }}
    >
      {NAV_WORKSPACE.map(({ tab: t, label }) => (
        <NavHighlight
          key={t}
          aria-label={label}
          active={tab === t}
          layoutId="mobile-primary-nav-highlight"
          onClick={() => { setTab(t); onNavigate?.(t) }}
          className={itemClass(tab === t)}
          contentClassName={contentClass}
        >
          <span className="[&>svg]:h-[18px] [&>svg]:w-[18px]">{ICONS[t]}</span>
          <span>{label}</span>
        </NavHighlight>
      ))}
      {NAV_LOCAL.map(({ route, label, icon: Icon }) => (
            <NavHighlight
              key={route}
              aria-label={label}
              active={tab === 'settings' && settingsRoute === route}
              layoutId="mobile-primary-nav-highlight"
              onClick={() => navigateSettings(route)}
              className={itemClass(tab === 'settings' && settingsRoute === route)}
              contentClassName={contentClass}
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={1.7} />
              <span>{label}</span>
            </NavHighlight>
      ))}
    </nav>
  )
}
