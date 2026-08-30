import { useRef, type KeyboardEvent, type PointerEvent, type ReactElement } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Bot, Search, ShieldCheck, Siren } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { useSidebar } from '@/components/ui/sidebar-context'
import { cn } from '@/lib/utils'
import {
  SIDEBAR_WIDTH_ICON,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
  clampSidebarWidth,
  collapseFromDrag,
} from '@/lib/sidebar-width'
import { stateTransition } from '@/components/layout'
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

/** 边界控件：上/下轨道只拖拽，居中按钮只切换；默认隐藏，热区 hover/键盘 focus 时出现 */
function SidebarEdge({ collapsed, width, onWidthChange }: { collapsed: boolean; width: number; onWidthChange: (w: number) => void }) {
  const { toggleSidebar, setOpen } = useSidebar()
  const dragState = useRef<{ startX: number; startW: number } | null>(null)
  const setDragging = (el: HTMLElement, on: boolean) => {
    const wrapper = el.closest('div[class*="sidebar-wrapper"]')
    if (!wrapper) return
    if (on) wrapper.setAttribute('data-dragging', '')
    else wrapper.removeAttribute('data-dragging')
  }
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    dragState.current = { startX: e.clientX, startW: collapsed ? SIDEBAR_WIDTH_ICON : width }
    setDragging(e.currentTarget, true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const drag = dragState.current
    if (!drag) return
    const next = drag.startW + (e.clientX - drag.startX)
    const nextCollapsed = collapseFromDrag(next, collapsed)
    if (nextCollapsed !== collapsed) setOpen(!nextCollapsed)
    if (!nextCollapsed) onWidthChange(clampSidebarWidth(next))
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    dragState.current = null
    setDragging(e.currentTarget, false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    if (collapsed) {
      if (e.key === 'ArrowRight') {
        setOpen(true)
        onWidthChange(SIDEBAR_WIDTH_MIN)
      }
      return
    }
    onWidthChange(clampSidebarWidth(width + (e.key === 'ArrowRight' ? 8 : -8)))
  }
  const track = 'pointer-events-auto absolute left-1/2 w-[6px] -translate-x-1/2 cursor-col-resize rounded-pill outline-none transition-colors hover:bg-sidebar-border/60 focus-visible:bg-sidebar-border'
  return (
    <div data-sidebar="edge" className="group/edge pointer-events-none absolute inset-y-0 -right-2 z-30 hidden w-4 sm:block">
      {/* 热区：仅负责 hover/focus 显示居中按钮 */}
      <div className="pointer-events-auto absolute inset-0" aria-hidden="true" />
      {/* 上/下轨道：只拖拽 */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整侧栏宽度"
        aria-valuemin={SIDEBAR_WIDTH_MIN}
        aria-valuemax={SIDEBAR_WIDTH_MAX}
        aria-valuenow={collapsed ? SIDEBAR_WIDTH_ICON : width}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyDown}
        className={cn(track, 'top-0 bottom-[calc(50%+28px)]')}
      />
      <div
        aria-hidden="true"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className={cn(track, 'bottom-0 top-[calc(50%+28px)]')}
      />
      {/* 居中按钮：只切换 */}
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        title={collapsed ? '展开侧栏' : '收起侧栏'}
        className="motion-interactive pointer-events-auto absolute left-1/2 top-1/2 z-10 grid h-9 w-5 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-border bg-surface text-muted/80 opacity-0 shadow-panel transition-opacity hover:text-fg focus-visible:opacity-100 group-hover/edge:opacity-100"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
          {collapsed ? <path d="M10 7l5 5-5 5" /> : <path d="M14 7l-5 5 5 5" />}
        </svg>
      </button>
    </div>
  )
}

/** shadcn 官方 Sidebar：collapsible=icon，滑动高亮保留；品牌归左栏，切换/拖拽归边界控件 */
export function AppSidebar({ onNavigate, width, onWidthChange }: { onNavigate?: (t: Tab) => void; width: number; onWidthChange: (w: number) => void }) {
  const { attention } = useTasks()
  const { tab, setTab, navigateSettings, settingsRoute } = useApp()
  const { state, isMobile, setOpenMobile } = useSidebar()
  const collapsed = state === 'collapsed'
  const reduceMotion = useReducedMotion()
  const activeRoute = tab === 'settings' ? settingsRoute : null
  /** 移动端 Sheet 内点击导航后关闭 Sheet */
  const done = () => {
    if (isMobile) setOpenMobile(false)
  }
  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader>
        {/* 单一行 + 宽度/透明度动画：收起时 AA 与菜单图标同轴居中，展开时左对齐，无条件切换跳变 */}
        <div className="flex items-center gap-2 overflow-hidden px-2 text-body font-bold transition-[padding] duration-200 ease-linear group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <span className="-ml-[5px] grid h-[26px] w-[26px] shrink-0 place-items-center rounded-sm bg-fg font-mono text-meta font-bold text-surface transition-[margin-left] duration-200 ease-linear group-data-[collapsible=icon]:ml-[8px]">AA</span>
          <span className="max-w-[160px] whitespace-nowrap overflow-hidden transition-[max-width,opacity] duration-200 ease-linear group-data-[collapsible=icon]:max-w-0 group-data-[collapsible=icon]:opacity-0">资产 Agent</span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>工作区</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_WORKSPACE.map(({ tab: t, label }) => (
                <SidebarMenuItem key={t}>
                  <SidebarMenuButton
                    isActive={tab === t}
                    tooltip={label}
                    title={label}
                    onClick={() => {
                      setTab(t)
                      onNavigate?.(t)
                      done()
                    }}
                    className="relative isolate data-[active=true]:bg-transparent group-data-[collapsible=icon]:mx-auto"
                  >
                    {tab === t && (
                      <motion.span layoutId="primary-nav-highlight" className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent" transition={stateTransition(reduceMotion)} aria-hidden="true" />
                    )}
                    {ICONS[t]}
                    <span className="truncate transition-opacity duration-150 group-data-[collapsible=icon]:opacity-0">{label}</span>
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
                    tooltip={label}
                    title={label}
                    onClick={() => {
                      navigateSettings(route)
                      onNavigate?.('settings')
                      done()
                    }}
                    className="relative isolate data-[active=true]:bg-transparent group-data-[collapsible=icon]:mx-auto"
                  >
                    {activeRoute === route && (
                      <motion.span layoutId="primary-nav-highlight" className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent" transition={stateTransition(reduceMotion)} aria-hidden="true" />
                    )}
                    <Icon className="h-4 w-4 shrink-0" strokeWidth={1.7} />
                    <span className="truncate transition-opacity duration-150 group-data-[collapsible=icon]:opacity-0">{label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarEdge collapsed={collapsed} width={width} onWidthChange={onWidthChange} />
    </Sidebar>
  )
}
