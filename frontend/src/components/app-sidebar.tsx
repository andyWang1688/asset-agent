import type { ReactElement } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Bot, Search, ShieldCheck, Siren } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { NavHighlight, stateTransition } from '@/components/layout'
import { useTasks } from '@/hooks/use-tasks'
import { useApp, type SettingsRoute, type Tab } from '@/store/app-state'

const APP_VERSION = 'v1.0.0'

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

function NavGroup({
  label,
  items,
  taskCount,
  onNavigate,
}: {
  label: string
  items: NavItemDef[]
  taskCount: number
  onNavigate?: (t: Tab) => void
}) {
  const { tab, setTab } = useApp()
  const reduceMotion = useReducedMotion()
  return (
    <>
      <div className="px-2.5 pb-1.5 font-mono text-meta tracking-wide text-muted">{label}</div>
      <nav className="mb-5 grid gap-[3px]">
        {items.map(({ tab: t, label: l }) => (
          <NavHighlight
            key={t}
            active={tab === t}
            layoutId="primary-nav-highlight"
            onClick={() => {
              setTab(t)
              onNavigate?.(t)
            }}
            className={tab === t ? 'w-full rounded-md text-left text-panel font-semibold text-fg' : 'w-full rounded-md text-left text-panel text-muted hover:bg-soft hover:text-fg'}
            contentClassName="flex w-full items-center gap-2.5 px-2.5 py-2"
          >
            {ICONS[t]}
            {l}
            {t === 'tasks' && taskCount > 0 && (
              <AnimatePresence mode="popLayout" initial={false}>
              <motion.span key={taskCount} className="ml-auto" initial={reduceMotion ? false : { opacity: 0, y: 'calc(-1 * var(--spacing-compact))' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, y: 'var(--spacing-compact)' }} transition={stateTransition(reduceMotion)}>
                <Badge variant="muted" className="font-mono">
                  {taskCount}
                </Badge>
              </motion.span>
              </AnimatePresence>
            )}
          </NavHighlight>
        ))}
      </nav>
    </>
  )
}

function SettingsNav({ onNavigate }: { onNavigate?: (t: Tab) => void }) {
  const { tab, navigateSettings, settingsRoute } = useApp()
  const activeRoute = tab === 'settings' ? settingsRoute : null
  return (
    <>
      <div className="px-2.5 pb-1.5 font-mono text-meta tracking-wide text-muted">本地设置</div>
      <nav className="mb-5 grid gap-[3px]" aria-label="本地设置">
        {NAV_LOCAL.map(({ route, label, icon: Icon }) => (
          <NavHighlight
            key={route}
            active={activeRoute === route}
            layoutId="primary-nav-highlight"
            onClick={() => {
              navigateSettings(route)
              onNavigate?.('settings')
            }}
            className={activeRoute === route ? 'w-full rounded-md text-left text-panel font-semibold text-fg' : 'w-full rounded-md text-left text-panel text-muted hover:bg-soft hover:text-fg'}
            contentClassName="flex w-full items-center gap-2.5 px-2.5 py-2"
          >
            <Icon className="h-4 w-4 shrink-0" strokeWidth={1.7} />
            {label}
          </NavHighlight>
        ))}
      </nav>
    </>
  )
}

/** 设计稿侧栏：AA 品牌 + 工作区/本地设置导航 + 本地模式页脚 */
export function AppSidebar({ onNavigate }: { onNavigate?: (t: Tab) => void }) {
  const { attention } = useTasks()
  return (
    <aside className="sticky top-0 flex h-svh flex-col overflow-y-auto border-r border-border bg-surface px-3 pt-[18px]">
      <div className="flex items-center gap-2.5 px-2.5 pb-7 pt-1 text-body font-bold">
        <span className="grid h-[26px] w-[26px] place-items-center rounded-sm bg-fg font-mono text-meta font-bold text-surface">
          AA
        </span>
        资产 Agent
      </div>
      <NavGroup label="工作区" items={NAV_WORKSPACE} taskCount={attention.length} onNavigate={onNavigate} />
      <SettingsNav onNavigate={onNavigate} />
      <div className="mt-auto border-t border-border px-2.5 pb-0.5 pt-3.5 text-caption text-muted">
        <b className="mb-0.5 block font-semibold text-fg">本地模式</b>
        资料仅保存在此设备
        <span className="mt-2 block font-mono text-meta text-muted">{APP_VERSION}</span>
      </div>
    </aside>
  )
}

/** 移动端底部导航（≤820px 显示） */
export function MobileBottomNav({ onNavigate }: { onNavigate?: (t: Tab) => void }) {
  const { tab, setTab, navigateSettings, settingsRoute } = useApp()
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-[70] flex border-t border-border px-2 pb-[calc(6px+env(safe-area-inset-bottom))] pt-1.5 backdrop-blur-md"
      style={{ background: 'color-mix(in oklch, var(--color-surface) 92%, transparent)' }}
    >
      <NavHighlight
        aria-label="对话"
        active={tab === 'chat'}
        layoutId="mobile-primary-nav-highlight"
        onClick={() => { setTab('chat'); onNavigate?.('chat') }}
        className={tab === 'chat' ? 'flex-1 rounded-md font-semibold text-fg' : 'flex-1 rounded-md text-fg opacity-55'}
        contentClassName="flex flex-col items-center gap-[3px] px-1 py-[5px] text-[10.5px]"
      >
        <span className="[&>svg]:h-[18px] [&>svg]:w-[18px]">{ICONS.chat}</span>
        <span>对话</span>
      </NavHighlight>
      {NAV_LOCAL.map(({ route, label, icon: Icon }) => (
            <NavHighlight
              key={route}
              aria-label={label}
              active={tab === 'settings' && settingsRoute === route}
              layoutId="mobile-primary-nav-highlight"
              onClick={() => navigateSettings(route)}
              className={tab === 'settings' && settingsRoute === route ? 'flex-1 rounded-md font-semibold text-fg' : 'flex-1 rounded-md text-fg opacity-55'}
              contentClassName="flex flex-col items-center gap-[3px] px-1 py-[5px] text-[10.5px]"
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={1.7} />
              <span>{label}</span>
            </NavHighlight>
      ))}
    </nav>
  )
}
