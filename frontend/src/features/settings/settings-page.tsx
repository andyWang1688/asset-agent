import { useState, type ComponentType } from 'react'
import { AnimatePresence } from 'motion/react'
import { Bot, Search, ShieldCheck, Siren } from 'lucide-react'
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { PageShell, SectionCard } from '@/components/layout'
import { useApp } from '@/store/app-state'
import { useModels } from '@/hooks/use-models'
import { errMsg } from '@/lib/api'
import type { ModelRow } from '@/lib/types'
import { ModelCard, type ModelCardActions } from './model-card'
import { ModelSheet } from './model-sheet'
import { RetrievalSection } from './retrieval-section'
import { SecurityEventsSection } from './security-events-section'
import { SecurityPolicySection } from './security-policy-section'
import type { SettingsModule } from './settings-navigation'

const MODULES: { id: SettingsModule; title: string; description: string; icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { id: 'models', title: '模型配置', description: '管理知识库模型', icon: Bot },
  { id: 'retrieval', title: '检索配置', description: '配置语义召回与重排模型', icon: Search },
  { id: 'security', title: '安全策略', description: '管理检测规则与高级安全策略', icon: ShieldCheck },
  { id: 'events', title: '安全事件', description: '查看检测与处理记录', icon: Siren },
]

/** 设置页编排：模块区块各自独立成组件，页面只负责模型弹窗/删除确认等跨区块状态 */
export function SettingsPage() {
  const { refreshHealth, settingsRoute: activeModule, securityTab, setSecurityTab } = useApp()
  const models = useModels()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetRole, setSheetRole] = useState('knowledge')
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [deleting, setDeleting] = useState<ModelRow | null>(null)

  const openSheet = (role: string, model: ModelRow | null) => {
    setEditing(model)
    setSheetRole(role)
    setSheetOpen(true)
  }

  const groupProps = (role: 'knowledge' | 'security'): ModelCardActions => ({
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
    onEdit: (m: ModelRow) => openSheet(m.role || role, m),
    onDelete: (m: ModelRow) => setDeleting(m),
  })

  const activeDefinition = MODULES.find((module) => module.id === activeModule) ?? MODULES[0]

  return (
    <PageShell title={activeDefinition.title} description={activeDefinition.description}>
      <SectionCard className="min-w-0 min-h-0 flex-1 overflow-hidden" contentClassName="p-0">
        {activeModule === 'security' && (
          <SecurityPolicySection tab={securityTab} onTabChange={setSecurityTab} securityModels={models.security} securityModelActions={groupProps('security')} />
        )}
          {activeModule === 'models' && <section>
            <div className="flex justify-end border-b border-border px-cell py-3">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="compact" size="sm">
                    添加模型
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => openSheet('knowledge', null)}>知识库模型</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className="border-b border-border px-cell py-4">
              <div className="mb-2.5 flex items-center gap-2">
                <h3 className="text-panel font-semibold">知识库模型</h3>
                <Badge variant="accent">必配</Badge>
              </div>
              <p className="mb-2.5 text-caption text-muted">负责 Wiki 编译与知识问答；未配置或未激活时，提交资料与提问会被阻止。</p>
              {models.knowledge.length === 0 ? (
                <ModelCard m={null} emptyDesc="可添加 DeepSeek、GLM、OpenAI、Claude、通义、Kimi 或 OpenAI 兼容端点。" {...groupProps('knowledge')} />
              ) : (
                <AnimatePresence mode="popLayout">{models.knowledge.map((m, index) => <ModelCard key={m.id} index={index} m={m} emptyDesc="" {...groupProps('knowledge')} />)}</AnimatePresence>
              )}
            </div>

          </section>}

        {activeModule === 'retrieval' && <RetrievalSection />}
        {activeModule === 'events' && <SecurityEventsSection />}
      </SectionCard>

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
    </PageShell>
  )
}
