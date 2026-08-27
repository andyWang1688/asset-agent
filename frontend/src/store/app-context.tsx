import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import type { Health } from '@/lib/types'

export type Tab = 'chat' | 'wiki' | 'tasks' | 'settings'

const isSettingsRoute = () => window.location.pathname.startsWith('/settings') || window.location.hash.startsWith('#/settings')

interface AppState {
  tab: Tab
  setTab: (t: Tab) => void
  /** 切换到知识库并打开指定文档（问答引用 / Wiki 内链跳转） */
  openWikiDoc: (path: string) => void
  wikiPath: string | null
  health: Health | null
  refreshHealth: () => Promise<void>
}

const AppContext = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [tab, setTabState] = useState<Tab>(() => isSettingsRoute() ? 'settings' : 'chat')
  const [wikiPath, setWikiPath] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health())
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    void refreshHealth()
  }, [refreshHealth])

  const setTab = useCallback((next: Tab) => {
    setTabState(next)
    if (next === 'settings' && !isSettingsRoute()) window.history.pushState(null, '', '/settings/models')
    if (next !== 'settings' && isSettingsRoute()) window.history.pushState(null, '', '/')
  }, [])

  useEffect(() => {
    const onRouteChange = () => setTabState(isSettingsRoute() ? 'settings' : 'chat')
    window.addEventListener('popstate', onRouteChange)
    window.addEventListener('hashchange', onRouteChange)
    return () => {
      window.removeEventListener('popstate', onRouteChange)
      window.removeEventListener('hashchange', onRouteChange)
    }
  }, [])

  const openWikiDoc = useCallback((path: string) => {
    setWikiPath(path)
    setTab('wiki')
  }, [setTab])

  const value = useMemo(
    () => ({ tab, setTab, openWikiDoc, wikiPath, health, refreshHealth }),
    [tab, setTab, openWikiDoc, wikiPath, health, refreshHealth],
  )
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp 必须在 AppProvider 内使用')
  return ctx
}
