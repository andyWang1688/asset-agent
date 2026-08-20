import type { ReactElement } from 'react'
import { Badge } from '@/components/ui/badge'
import { useTasks } from '@/hooks/use-tasks'
import { useApp, type Tab } from '@/store/app-context'

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
const NAV_LOCAL: NavItemDef[] = [{ tab: 'settings', label: '设置' }]

function NavGroup({
  label,
  items,
  taskCount,
  onNavigate,
}: {
  label: string
  items: NavItemDef[]
  taskCount: number
  onNavigate?: () => void
}) {
  const { tab, setTab } = useApp()
  return (
    <>
      <div className="px-2.5 pb-1.5 font-mono text-meta tracking-wide text-muted">{label}</div>
      <nav className="mb-5 grid gap-[3px]">
        {items.map(({ tab: t, label: l }) => (
          <button
            key={t}
            type="button"
            aria-current={tab === t ? 'page' : undefined}
            onClick={() => {
              setTab(t)
              onNavigate?.()
            }}
            className={
              'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-panel transition-all duration-150 active:scale-[0.97] ' +
              (tab === t
                ? 'bg-soft font-semibold text-fg shadow-[inset_2px_0_var(--color-fg)]'
                : 'text-muted hover:bg-soft hover:text-fg')
            }
          >
            {ICONS[t]}
            {l}
            {t === 'tasks' && taskCount > 0 && (
              <span className="ml-auto">
                <Badge variant="muted" className="font-mono">
                  {taskCount}
                </Badge>
              </span>
            )}
          </button>
        ))}
      </nav>
    </>
  )
}

/** 设计稿侧栏：AA 品牌 + 工作区/本地设置导航 + 本地模式页脚 */
export function AppSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { attention } = useTasks()
  return (
    <aside className="sticky top-0 flex h-svh flex-col border-r border-border bg-surface px-3 pt-[18px]">
      <div className="flex items-center gap-2.5 px-2.5 pb-7 pt-1 text-body font-bold">
        <span className="grid h-[26px] w-[26px] place-items-center rounded-sm bg-fg font-mono text-meta font-bold text-surface">
          AA
        </span>
        资产助手
      </div>
      <NavGroup label="工作区" items={NAV_WORKSPACE} taskCount={attention.length} onNavigate={onNavigate} />
      <NavGroup label="本地设置" items={NAV_LOCAL} taskCount={0} onNavigate={onNavigate} />
      <div className="mt-auto border-t border-border px-2.5 pb-0.5 pt-3.5 text-caption text-muted">
        <b className="mb-0.5 block font-semibold text-fg">本地模式</b>
        资料仅保存在此设备
        <span className="mt-2 block font-mono text-meta text-muted">{APP_VERSION}</span>
      </div>
    </aside>
  )
}

/** 移动端底部导航（≤820px 显示） */
export function MobileBottomNav() {
  const { tab, setTab } = useApp()
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-[70] flex border-t border-border px-2 pb-[calc(6px+env(safe-area-inset-bottom))] pt-1.5 backdrop-blur-md"
      style={{ background: 'color-mix(in oklch, var(--color-surface) 92%, transparent)' }}
    >
      {[...NAV_WORKSPACE, ...NAV_LOCAL].map(({ tab: t, label }) => (
        <button
          key={t}
          type="button"
          aria-label={label}
          onClick={() => setTab(t)}
          className={
            'flex flex-1 flex-col items-center gap-[3px] rounded-md px-1 py-[5px] text-[10.5px] transition-colors duration-150 ' +
            (tab === t ? 'font-semibold text-fg' : 'text-fg opacity-55')
          }
        >
          <span className="[&>svg]:h-[18px] [&>svg]:w-[18px]">{ICONS[t]}</span>
          <span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
