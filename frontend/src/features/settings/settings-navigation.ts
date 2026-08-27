export const SETTINGS_MODULES = ['models', 'retrieval', 'rules', 'policy', 'events'] as const

export type SettingsModule = (typeof SETTINGS_MODULES)[number]

export function settingsModuleFromLocation(location: Pick<Location, 'pathname' | 'hash'>): SettingsModule {
  const pathModule = location.pathname.match(/^\/settings\/([^/]+)/)?.[1]
  const hashModule = location.hash.match(/^#\/settings\/([^/]+)/)?.[1]
  const candidate = pathModule ?? hashModule
  return SETTINGS_MODULES.includes(candidate as SettingsModule) ? (candidate as SettingsModule) : 'models'
}

export function setSettingsModuleUrl(module: SettingsModule): void {
  window.history.pushState(null, '', `/settings/${module}`)
}
