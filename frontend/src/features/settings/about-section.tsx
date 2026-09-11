import { CheckCircle2, CircleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Wordmark } from '@/brand-wordmark'
import { useApp } from '@/store/app-state'
import { SettingsGroup, SettingsRow } from './settings-ui'

/** 关于：版本、定位与数据位置；保险柜连接状态来自 health */
export function AboutSection() {
  const { health } = useApp()
  const vaultReady = !!health?.vaultwarden_configured
  return (
    <div className="flex flex-col gap-4">
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
