import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
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
import { useApp } from '@/store/app-context'
import { useModels } from '@/hooks/use-models'
import { api, errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ModelRow, SecurityEvent } from '@/lib/types'
import { ModelSheet } from './model-sheet'

function ModelCard({
  m,
  emptyDesc,
  emptyChip = '未激活',
  onAdd,
  onActivate,
  onTest,
  onEdit,
  onDelete,
}: {
  m: ModelRow | null
  emptyDesc: string
  emptyChip?: string
  onAdd: () => void
  onActivate: (id: number) => void
  onTest: (id: number) => Promise<unknown>
  onEdit: (m: ModelRow) => void
  onDelete: (m: ModelRow) => void
}) {
  const [testing, setTesting] = useState(false)
  return (
    <div className="mb-2 rounded-md border border-border bg-bg p-3 last:mb-0">
      <strong className="text-caption font-semibold">{m ? m.name : '尚未配置'}</strong>
      <p className="mt-1 break-words font-mono text-meta text-muted">
        {m ? `${m.base_url || ''}${m.model ? ` · ${m.model}` : ''}` : emptyDesc}
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Badge variant={m?.is_active ? 'accent' : 'muted'}>{m ? (m.is_active ? '激活' : '未激活') : emptyChip}</Badge>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {m ? (
            <>
              {!m.is_active && (
                <Button variant="compact" size="sm" onClick={() => onActivate(m.id)}>
                  激活
                </Button>
              )}
              <Button
                variant="compact"
                size="sm"
                disabled={testing}
                onClick={() => {
                  setTesting(true)
                  void onTest(m.id).finally(() => setTesting(false))
                }}
              >
                {testing ? '测试中…' : '测试'}
              </Button>
              <Button variant="compact" size="sm" onClick={() => onEdit(m)}>
                编辑
              </Button>
              <Button variant="danger" size="sm" onClick={() => onDelete(m)}>
                删除
              </Button>
            </>
          ) : (
            <Button variant="compact" size="sm" onClick={onAdd}>
              添加模型
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { refreshHealth } = useApp()
  const models = useModels()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetRole, setSheetRole] = useState('knowledge')
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [deleting, setDeleting] = useState<ModelRow | null>(null)
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [policyOpen, setPolicyOpen] = useState(false)
  const [policyYaml, setPolicyYaml] = useState('')
  const [policyLoaded, setPolicyLoaded] = useState(false)
  const [policySaving, setPolicySaving] = useState(false)
  const [policyError, setPolicyError] = useState('')

  const loadEvents = () => {
    void api.securityEvents().then(setEvents).catch(() => setEvents([]))
  }
  useEffect(() => {
    loadEvents()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadPolicy = async () => {
    if (policyLoaded) return
    setPolicyError('')
    try {
      const r = await api.policy()
      setPolicyYaml(r.yaml || '')
      setPolicyLoaded(true)
    } catch (e) {
      setPolicyError(errMsg(e))
    }
  }

  const openSheet = (role: string, model: ModelRow | null) => {
    setEditing(model)
    setSheetRole(role)
    setSheetOpen(true)
  }

  const groupProps = (role: 'knowledge' | 'security') => ({
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

  return (
    <>
      <h1 className="page-heading">设置</h1>
      <p className="page-sub">管理模型角色、安全策略和安全事件。知识库模型是提交资料与知识问答的前置条件。</p>

      <div className="mt-7 max-w-[860px]">
        <div className="mb-4 overflow-hidden rounded-lg border border-border bg-surface shadow-panel [&>section+section]:border-t [&>section+section]:border-border">
          <section>
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-[17px] py-4">
              <div>
                <h2 className="text-input font-semibold">模型配置</h2>
                <p className="mt-1 text-caption text-muted">每个角色同时只能激活一个模型配置。</p>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="compact" size="sm">
                    添加模型
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => openSheet('knowledge', null)}>知识库模型</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => openSheet('security', null)}>安全增强模型</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className="border-b border-border px-[17px] py-4">
              <div className="mb-2.5 flex items-center gap-2">
                <h3 className="text-panel font-semibold">知识库模型</h3>
                <Badge variant="accent">必配</Badge>
              </div>
              <p className="mb-2.5 text-caption text-muted">负责 Wiki 编译与知识问答；未配置或未激活时，提交资料与提问会被阻止。</p>
              {models.knowledge.length === 0 ? (
                <ModelCard m={null} emptyDesc="可添加 DeepSeek、GLM、OpenAI、Claude、通义、Kimi 或 OpenAI 兼容端点。" {...groupProps('knowledge')} />
              ) : (
                models.knowledge.map((m) => <ModelCard key={m.id} m={m} emptyDesc="" {...groupProps('knowledge')} />)
              )}
            </div>

            <div className="px-[17px] py-4">
              <div className="mb-2.5 flex items-center gap-2">
                <h3 className="text-panel font-semibold">安全增强模型</h3>
                <Badge variant="muted">可选</Badge>
              </div>
              <p className="mb-2.5 text-caption text-muted">
                仅在本地检测之后增强敏感信息识别；只接受本机或内网端点，发送给模型的内容已脱敏。
              </p>
              {models.security.length === 0 ? (
                <ModelCard
                  m={null}
                  emptyDesc="未配置时，系统继续使用本地规则、上下文与熵值检测。"
                  emptyChip="本地检测生效"
                  {...groupProps('security')}
                />
              ) : (
                models.security.map((m) => <ModelCard key={m.id} m={m} emptyDesc="" {...groupProps('security')} />)
              )}
            </div>
          </section>

          <section>
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-[17px] py-4">
              <div>
                <h2 className="text-input font-semibold">高级安全策略</h2>
                <p className="mt-1 text-caption text-muted">编辑 config/policy.yaml；默认折叠。</p>
              </div>
              <Button
                variant="compact"
                size="sm"
                onClick={() => {
                  setPolicyOpen(!policyOpen)
                  if (!policyOpen) void loadPolicy()
                }}
              >
                {policyOpen ? '收起' : '展开'}
              </Button>
            </div>
            {policyOpen && (
              <div className="px-[17px] py-4">
                <Textarea
                  value={policyYaml}
                  spellCheck={false}
                  placeholder={policyLoaded ? '' : '正在加载策略…'}
                  onChange={(e) => setPolicyYaml(e.target.value)}
                  className="min-h-[145px] bg-bg font-mono text-meta leading-[1.55]"
                />
                <div className="mt-2.5 flex items-center gap-2.5">
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={policySaving}
                    onClick={() => {
                      setPolicySaving(true)
                      void api
                        .savePolicy(policyYaml)
                        .then(() => toast.success('安全策略已校验并保存'))
                        .catch((e) => setPolicyError(errMsg(e)))
                        .finally(() => setPolicySaving(false))
                    }}
                  >
                    {policySaving ? '保存中…' : '保存策略'}
                  </Button>
                  {policyError && <p className="text-caption text-danger">{policyError}</p>}
                </div>
              </div>
            )}
          </section>

          <section>
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-[17px] py-4">
              <div>
                <h2 className="text-input font-semibold">安全事件</h2>
                <p className="mt-1 text-caption text-muted">最近的检测、闸门与后台处理记录。</p>
              </div>
              <Button variant="compact" size="sm" onClick={loadEvents}>
                刷新
              </Button>
            </div>
            {events.length === 0 ? (
              <div className="flex items-baseline gap-2.5 px-[17px] py-3 text-caption text-muted">
                <span className="flex-1">暂无安全事件</span>
                <Badge variant="muted">0</Badge>
              </div>
            ) : (
              events.slice(0, 20).map((r) => (
                <div key={r.id} className="flex items-baseline gap-2.5 border-t border-border px-[17px] py-3 text-caption first:border-t-0">
                  <Badge variant="muted">{r.kind}</Badge>
                  <span className={cn('min-w-0 flex-1 break-words text-fg')}>{r.detail}</span>
                  <time className="ml-auto whitespace-nowrap font-mono text-meta text-muted">{fmtTime(r.created_at)}</time>
                </div>
              ))
            )}
          </section>
        </div>
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
    </>
  )
}
