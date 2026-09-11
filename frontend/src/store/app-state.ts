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
  /** 私密引用安全元数据卡 */
  privateRefId: string | null
  openPrivateRef: (refId: string) => void
  closePrivateRef: () => void
  /** 从任务详情等入口回到原会话 */
  pendingSession: string | null
  requestOpenSession: (sessionId: string) => void
  consumeOpenSession: () => void
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
