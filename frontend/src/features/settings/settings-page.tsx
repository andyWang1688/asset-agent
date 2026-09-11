import { useState } from 'react'
import { CircleAlert, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { useApp } from '@/store/app-state'
import { useModels } from '@/hooks/use-models'
import { errMsg } from '@/lib/api'
import type { ModelRow as ModelRowType } from '@/lib/types'
import { ModelRow, type ModelRowActions } from './model-row'
import { ModelSheet } from './model-sheet'
import { AboutSection } from './about-section'
import { RetrievalSection } from './retrieval-section'
import { SecurityEventsSection } from './security-events-section'
import { SecurityPolicySection } from './security-policy-section'
import { SettingsGroup, SettingsRow } from './settings-ui'
import type { SettingsModule } from './settings-navigation'

const MODULES: { id: SettingsModule; label: string }[] = [
  { id: 'models', label: '模型配置' },
  { id: 'retrieval', label: '检索配置' },
  { id: 'security', label: '安全策略' },
  { id: 'events', label: '安全事件' },
  { id: 'about', label: '关于' },
]

function ModelsPanel({
  knowledge,
  security,
  actions,
}: {
  knowledge: ModelRowType[]
  security: ModelRowType[]
  actions: ModelRowActions
}) {
  return (
    <div className="flex flex-col gap-4">
      <SettingsGroup
        title="知识库模型"
        badge={<Badge variant="outline">必配</Badge>}
        description="负责 Wiki 编译与知识问答；未配置或未激活时，提交资料与提问会被阻止。"
        action={
          <Button size="sm" variant="outline" onClick={actions.onAdd}>
            <Plus data-icon="inline-start" />
            添加模型
          </Button>
        }
      >
        {knowledge.length === 0 ? (
          <SettingsRow
            label={
              <span className="inline-flex items-center gap-1.5 text-destructive">
                <CircleAlert className="size-3.5" />
                未配置
              </span>
            }
            description="可添加 DeepSeek、GLM、OpenAI、Claude、通义、Kimi 或 OpenAI 兼容端点。"
            control={
              <Button size="sm" variant="outline" onClick={actions.onAdd}>
                添加模型
              </Button>
            }
          />
        ) : (
          knowledge.map((model) => <ModelRow key={model.id} m={model} {...actions} />)
        )}
      </SettingsGroup>

      <SettingsGroup
        title="安全增强模型"
        badge={<Badge variant="outline">可选</Badge>}
        description="本地 AI 辅检，只加严不放松；未配置时继续使用本地检测，仅允许本机或内网端点。"
        action={
          <Button size="sm" variant="outline" onClick={actions.onAdd}>
            <Plus data-icon="inline-start" />
            添加模型
          </Button>
        }
      >
        {security.length === 0 ? (
          <SettingsRow
            label={
              <span className="inline-flex items-center gap-1.5 text-amber-600">
                <CircleAlert className="size-3.5" />
                未配置
              </span>
            }
            description="使用本地正则与熵值检测。"
            control={
              <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={actions.onAdd}>
                添加
              </Button>
            }
          />
        ) : (
          security.map((model) => <ModelRow key={model.id} m={model} {...actions} />)
        )}
      </SettingsGroup>
    </div>
  )
}

/** 设置页编排：模块切换走 URL；模型弹窗/删除确认等跨区块状态在此持有 */
export function SettingsPage() {
  const { refreshHealth, settingsRoute: activeModule, navigateSettings } = useApp()
  const models = useModels()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetRole, setSheetRole] = useState('knowledge')
  const [editing, setEditing] = useState<ModelRowType | null>(null)
  const [deleting, setDeleting] = useState<ModelRowType | null>(null)

  const openSheet = (role: string, model: ModelRowType | null) => {
    setEditing(model)
    setSheetRole(role)
    setSheetOpen(true)
  }

  const groupProps = (role: 'knowledge' | 'security'): ModelRowActions => ({
    onAdd: () => openSheet(role, null),
    onActivate: (id: number) => {
      void models.activate(id).then(() => {
        toast.success('已激活')
        void refreshHealth()
      })
    },
    onTest: async (id: number) => {
      const r = await models.test(id)
      if (r.ok) toast.success('连通成功：' + (r.reply || ''))
      else toast.error('连通失败：' + (r.error || '未知错误'))
    },
    onEdit: (m: ModelRowType) => openSheet(m.role || role, m),
    onDelete: (m: ModelRowType) => setDeleting(m),
  })

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex w-full flex-col gap-4 px-4 py-4">
        <SegmentedTabs
          aria-label="设置模块"
          value={activeModule}
          onChange={(value) => navigateSettings(value)}
          options={MODULES.map((module) => ({ value: module.id, label: module.label }))}
        />

        {activeModule === 'models' && (
          <ModelsPanel knowledge={models.knowledge} security={models.security} actions={groupProps('knowledge')} />
        )}
        {activeModule === 'retrieval' && <RetrievalSection />}
        {activeModule === 'security' && (
          <SecurityPolicySection securityModels={models.security} securityModelActions={groupProps('security')} />
        )}
        {activeModule === 'events' && <SecurityEventsSection />}
        {activeModule === 'about' && <AboutSection />}
      </div>

      <ModelSheet
        open={sheetOpen}
        role={sheetRole}
        model={editing}
        presets={models.presets}
        onSave={async (body) => {
          await models.save(body)
          toast.success('模型配置已保存')
          void refreshHealth()
        }}
        onClose={() => setSheetOpen(false)}
      />

      <AlertDialog open={!!deleting} onOpenChange={(o) => { if (!o) setDeleting(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除模型配置？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除「{deleting?.name}」的配置（API Key 密文一并销毁），此操作不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (!deleting) return
                void models
                  .remove(deleting.id)
                  .then(() => {
                    toast.success('已删除')
                    void refreshHealth()
                  })
                  .catch((e) => toast.error('删除失败：' + errMsg(e)))
                  .finally(() => setDeleting(null))
              }}
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
