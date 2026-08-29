import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import type { Health } from '@/lib/types'
import { AppContext, type SettingsRoute, type Tab } from '@/store/app-state'
import { securityTabFromHash, settingsModuleFromLocation, type SecurityTab } from '@/features/settings/settings-navigation'

/** 各顶级页面对应的 URL；chat 为根路径 */
const TAB_PATH: Record<Tab, string> = { chat: '/', wiki: '/wiki', tasks: '/tasks', settings: '/settings/models' }

const tabFromLocation = (): Tab => {
  const { pathname, hash } = window.location
  if (pathname.startsWith('/settings') || hash.startsWith('#/settings')) return 'settings'
  if (pathname.startsWith('/wiki')) return 'wiki'
  if (pathname.startsWith('/tasks')) return 'tasks'
  return 'chat'
}

const isSettingsRoute = () => tabFromLocation() === 'settings'

/** URL 是唯一来源；Provider 是唯一订阅 popstate/hashchange 的地方 */
const routeFromLocation = () => ({
  tab: tabFromLocation(),
  settingsRoute: settingsModuleFromLocation(window.location),
  securityTab: securityTabFromHash(window.location.hash),
})

export function AppProvider({ children }: { children: ReactNode }) {
  const [wikiPath, setWikiPath] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [tab, setTabState] = useState<Tab>(() => routeFromLocation().tab)
  const [settingsRoute, setSettingsRoute] = useState<SettingsRoute>(() => routeFromLocation().settingsRoute)
  const [securityTab, setSecurityTabState] = useState<SecurityTab>(() => routeFromLocation().securityTab)

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
    if (next === 'settings') {
      if (!isSettingsRoute()) {
        window.history.pushState(null, '', TAB_PATH.settings)
        setSettingsRoute('models')
      }
      return
    }
    // chat/wiki/tasks 各自拥有 URL，刷新与直开可恢复
    if (window.location.pathname !== TAB_PATH[next]) window.history.pushState(null, '', TAB_PATH[next])
  }, [])

  const navigateSettings = useCallback((route: SettingsRoute) => {
    window.history.pushState(null, '', `/settings/${route}${route === 'security' ? '#regex' : ''}`)
    setSettingsRoute(route)
    if (route === 'security') setSecurityTabState('regex')
    setTabState('settings')
  }, [])

  const setSecurityTab = useCallback((next: SecurityTab) => {
    window.history.replaceState(null, '', `/settings/security#${next}`)
    setSecurityTabState(next)
  }, [])

  useEffect(() => {
    const onRouteChange = () => {
      const next = routeFromLocation()
      setTabState(next.tab)
      setSettingsRoute(next.settingsRoute)
      setSecurityTabState(next.securityTab)
    }
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
    () => ({ tab, setTab, openWikiDoc, wikiPath, health, refreshHealth, navigateSettings, settingsRoute, securityTab, setSecurityTab }),
    [tab, setTab, openWikiDoc, wikiPath, health, refreshHealth, navigateSettings, settingsRoute, securityTab, setSecurityTab],
  )
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}
