import { createContext, useContext } from 'react'
import type { Health } from '@/lib/types'
import type { SecurityTab, SettingsModule } from '@/features/settings/settings-navigation'

export type SettingsRoute = SettingsModule
export type Tab = 'chat' | 'wiki' | 'tasks' | 'settings'

export interface AppState {
  tab: Tab
  setTab: (t: Tab) => void
  openWikiDoc: (path: string) => void
  wikiPath: string | null
  health: Health | null
  refreshHealth: () => Promise<void>
  navigateSettings: (route: SettingsRoute) => void
  settingsRoute: SettingsRoute
  /** 安全策略二级标签（URL hash 为唯一来源，Provider 统一同步） */
  securityTab: SecurityTab
  setSecurityTab: (tab: SecurityTab) => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp 必须在 AppProvider 内使用')
  return ctx
}
