export const SETTINGS_MODULES = ['models', 'retrieval', 'security', 'events'] as const

export type SettingsModule = (typeof SETTINGS_MODULES)[number]

export function settingsModuleFromLocation(location: Pick<Location, 'pathname' | 'hash'>): SettingsModule {
  const pathModule = location.pathname.match(/^\/settings\/([^/]+)/)?.[1]
  const hashModule = location.hash.match(/^#\/settings\/([^/]+)/)?.[1]
  const candidate = pathModule ?? hashModule
  if (candidate === 'rules' || candidate === 'policy') return 'security'
  return SETTINGS_MODULES.includes(candidate as SettingsModule) ? (candidate as SettingsModule) : 'models'
}
