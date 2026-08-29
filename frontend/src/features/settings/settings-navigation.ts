export type SettingsModule = 'models' | 'retrieval' | 'security' | 'events'

export type SecurityTab = 'regex' | 'keywords' | 'entropy' | 'security-model'

export const SECURITY_TABS: { id: SecurityTab; label: string }[] = [
  { id: 'regex', label: '正则' },
  { id: 'keywords', label: '关键词' },
  { id: 'entropy', label: '熵值判定' },
  { id: 'security-model', label: '安全增强模型' },
]

export function settingsModuleFromLocation(location: Pick<Location, 'pathname' | 'hash'>): SettingsModule {
  const pathModule = location.pathname.match(/^\/settings\/([^/]+)/)?.[1]
  const hashModule = location.hash.match(/^#\/settings\/([^/]+)/)?.[1]
  const candidate = pathModule ?? hashModule
  if (candidate === 'rules' || candidate === 'policy') return 'security'
  return candidate === 'retrieval' || candidate === 'security' || candidate === 'events' ? candidate : 'models'
}

/** 安全策略页的二级标签来自 hash（如 #keywords），非法值回落到正则页 */
export function securityTabFromHash(hash: string): SecurityTab {
  const value = hash.replace(/^#/, '')
  return SECURITY_TABS.some((tab) => tab.id === value) ? (value as SecurityTab) : 'regex'
}
