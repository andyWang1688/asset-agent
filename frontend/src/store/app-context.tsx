import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import type { Health } from '@/lib/types'
import { AppContext, type SettingsRoute, type Tab } from '@/store/app-state'

const isSettingsRoute = () => window.location.pathname.startsWith('/settings') || window.location.hash.startsWith('#/settings')
const settingsRouteFromLocation = (): SettingsRoute => {
  const candidate = window.location.pathname.match(/^\/settings\/([^/]+)/)?.[1]
    ?? window.location.hash.match(/^#\/settings\/([^/]+)/)?.[1]
  if (candidate === 'rules' || candidate === 'policy') return 'security'
  return candidate === 'retrieval' || candidate === 'security' || candidate === 'events' ? candidate : 'models'
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [tab, setTabState] = useState<Tab>(() => isSettingsRoute() ? 'settings' : 'chat')
  const [wikiPath, setWikiPath] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [settingsRoute, setSettingsRoute] = useState<SettingsRoute>(settingsRouteFromLocation)

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

  const navigateSettings = useCallback((route: SettingsRoute) => {
    window.history.pushState(null, '', `/settings/${route}${route === 'security' ? '#regex' : ''}`)
    setSettingsRoute(route)
    setTabState('settings')
  }, [])

  useEffect(() => {
    const onRouteChange = () => {
      setTabState(isSettingsRoute() ? 'settings' : 'chat')
      setSettingsRoute(settingsRouteFromLocation())
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
    () => ({ tab, setTab, openWikiDoc, wikiPath, health, refreshHealth, navigateSettings, settingsRoute }),
    [tab, setTab, openWikiDoc, wikiPath, health, refreshHealth, navigateSettings, settingsRoute],
  )
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}
