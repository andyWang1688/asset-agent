import { useState } from 'react'
import { CheckCircle2, CircleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { Wordmark } from '@/brand-wordmark'
import { readTheme, setTheme, type Theme } from '@/lib/theme'
import { useApp } from '@/store/app-state'
import { SettingsGroup, SettingsRow } from './settings-ui'

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]

/** 通用：外观（主题）、版本与定位、数据位置；保险柜连接状态来自 health */
export function GeneralSection() {
  const { health } = useApp()
  const vaultReady = !!health?.vaultwarden_configured
  const [theme, setThemeState] = useState<Theme>(() => readTheme())
  const chooseTheme = (t: Theme) => {
    setThemeState(t)
    setTheme(t)
  }
  return (
    <div className="flex flex-col gap-4">
      <SettingsGroup title="外观" description="跟随系统时会随系统深浅色自动切换。">
        <SettingsRow
          label="主题"
          control={<SegmentedTabs aria-label="主题" value={theme} onChange={chooseTheme} options={THEME_OPTIONS} />}
        />
      </SettingsGroup>
      <SettingsGroup
        title="知守 Memo"
        badge={<Badge variant="outline">v1.0.0</Badge>}
        description="本地个人资产助手：把私人资料安全收好、整理成知识库，随时可问。资料不出本机。"
      >
        <div className="px-4 py-5">
          <Wordmark className="h-8 w-auto text-foreground" />
        </div>
      </SettingsGroup>
      <SettingsGroup title="数据与隐私" description="所有内容仅保存在本机，应用不上传任何资料。">
        <SettingsRow
          label="知识库目录"
          description="Wiki 与索引的存放位置。"
          control={<span className="font-mono text-xs text-muted-foreground">~/AssetAgent/workspace/wiki</span>}
        />
        <SettingsRow
          label="原件目录（Private Raw）"
          description="应用只告知位置，不提供浏览、读取或导出。"
          control={<span className="font-mono text-xs text-muted-foreground">~/AssetAgent/private_raw</span>}
        />
        <SettingsRow
          label="密码保险柜"
          description="敏感值只存于 Vaultwarden，Wiki 中仅保留私密引用。"
          control={
            vaultReady ? (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
                <CheckCircle2 className="size-3.5" />
                已连接
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs text-amber-600">
                <CircleAlert className="size-3.5" />
                未配置
              </span>
            )
          }
        />
      </SettingsGroup>
    </div>
  )
}
