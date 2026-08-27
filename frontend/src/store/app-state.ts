import { createContext, useContext } from 'react'
import type { Health } from '@/lib/types'

export type SettingsRoute = 'models' | 'retrieval' | 'security' | 'events'
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
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp 必须在 AppProvider 内使用')
  return ctx
}
