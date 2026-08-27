import { useCallback, useEffect, useState, type ComponentType } from 'react'
import { Bot, ChevronLeft, ChevronRight, RefreshCw, Search, ShieldCheck, Siren } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import { useApp } from '@/store/app-state'
import { useModels } from '@/hooks/use-models'
import { api, errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ModelRow, SecurityEvent, SecurityMode } from '@/lib/types'
import { ModelSheet } from './model-sheet'
import { RetrievalSection } from './retrieval-section'
import type { SettingsModule } from './settings-navigation'

const MODULES: { id: SettingsModule; title: string; description: string; icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { id: 'models', title: '模型配置', description: '管理知识库与安全增强模型', icon: Bot },
  { id: 'retrieval', title: '检索配置', description: '配置语义召回与重排模型', icon: Search },
  { id: 'security', title: '安全策略', description: '管理检测规则与高级安全策略', icon: ShieldCheck },
  { id: 'events', title: '安全事件', description: '查看检测与处理记录', icon: Siren },
]

/** 去掉后端表单错误的字段路径前缀（detection.extra_rules[0].），保留友好信息 */
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

type SecurityTab = 'regex' | 'keywords' | 'entropy' | 'security-model'

const SECURITY_TABS: { id: SecurityTab; label: string }[] = [
  { id: 'regex', label: '正则' },
  { id: 'keywords', label: '关键词' },
  { id: 'entropy', label: '熵值判定' },
  { id: 'security-model', label: '安全增强模型' },
]

const securityTabFromHash = (): SecurityTab => {
  const value = window.location.hash.replace(/^#/, '')
  return SECURITY_TABS.some((tab) => tab.id === value) ? value as SecurityTab : 'regex'
}

function SecurityPolicySkeleton({
  mode,
  loading,
  onModeChange,
  tab,
  onTabChange,
}: {
  mode: SecurityMode
  loading: boolean
  onModeChange: (mode: SecurityMode) => void
  tab: SecurityTab
  onTabChange: (tab: SecurityTab) => void
}) {
  return (
    <section>
      <div className="border-b border-border px-[17px] py-4">
        <h3 className="text-panel font-semibold">处理方式</h3>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {([
            ['default', '默认模式', '扫描后按既定规则自动处理，无需人工步骤。'],
            ['confirm', '确认模式', '每份资料入库前先过确认页，逐份看一眼。'],
          ] as const).map(([value, label, description]) => (
            <label key={value} className={cn('flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 transition-colors', mode === value ? 'border-fg/45 bg-soft' : 'border-border')}>
              <input
                type="radio"
                name="security-mode"
                value={value}
                checked={mode === value}
                disabled={loading}
                onChange={() => onModeChange(value)}
                className="mt-1 accent-[var(--color-fg)]"
              />
              <span>
                <strong className="block text-caption font-semibold">{label}</strong>
                <span className="mt-0.5 block text-meta text-muted">{description}</span>
              </span>
            </label>
          ))}
        </div>
        <div className="mt-2.5 rounded-md bg-bg px-3 py-2 text-caption text-muted">
          <strong className="font-semibold text-fg">永远生效</strong>：秘密原文永不发给模型；对话发凭证一律拦截；回答永远复扫。
        </div>
      </div>
      <div>
        <div className="border-b border-border px-[17px] pt-3">
          <h3 className="mb-2.5 text-panel font-semibold">配置细则</h3>
          <nav className="flex flex-wrap gap-1" aria-label="安全策略配置细则">
            {SECURITY_TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                aria-current={tab === id ? 'page' : undefined}
                onClick={() => onTabChange(id)}
                className={cn('rounded-t-md border-b-2 px-3 py-2 text-caption transition-colors', tab === id ? 'border-fg font-semibold text-fg' : 'border-transparent text-muted hover:text-fg')}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
        <div className="px-[17px] py-8 text-center text-caption text-muted">此配置页内容即将加载</div>
      </div>
    </section>
  )
}

export function SettingsPage() {
  const { refreshHealth, settingsRoute: activeModule, tab } = useApp()
  const models = useModels()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetRole, setSheetRole] = useState('knowledge')
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [deleting, setDeleting] = useState<ModelRow | null>(null)
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [eventPage, setEventPage] = useState(1)
  const [securityMode, setSecurityMode] = useState<SecurityMode>('default')
  const [securityLoading, setSecurityLoading] = useState(false)
  const [securityTab, setSecurityTab] = useState<SecurityTab>(securityTabFromHash)

  const loadEvents = useCallback(async () => {
    setEventsLoading(true)
    try {
      setEvents(await api.securityEvents())
    } catch {
      setEvents([])
    } finally {
      setEventsLoading(false)
    }
  }, [])
  useEffect(() => {
    if (tab !== 'settings' || activeModule !== 'events') return
    setEventPage(1)
    void loadEvents()
    const timer = window.setInterval(() => void loadEvents(), 5000)
    return () => window.clearInterval(timer)
  }, [activeModule, loadEvents, tab])
  useEffect(() => {
    void api.securitySettings().then((result) => setSecurityMode(result.mode)).catch(() => {})
  }, [])
  useEffect(() => {
    const onHashChange = () => setSecurityTab(securityTabFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const updateSecurityMode = async (next: SecurityMode) => {
    const previous = securityMode
    setSecurityMode(next)
    setSecurityLoading(true)
    try {
      const result = await api.updateSecuritySettings({ mode: next })
      setSecurityMode(result.mode)
      toast.success('处理方式已更新')
    } catch (e) {
      setSecurityMode(previous)
      toast.error('处理方式更新失败：' + errMsg(e))
    } finally {
      setSecurityLoading(false)
    }
  }

  const changeSecurityTab = (next: SecurityTab) => {
    window.history.replaceState(null, '', `/settings/security#${next}`)
    setSecurityTab(next)
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

  const activeDefinition = MODULES.find((module) => module.id === activeModule) ?? MODULES[0]
  const ActiveIcon = activeDefinition.icon

  return (
    <>
      <h1 className="page-heading">设置中心</h1>
      <p className="page-sub">管理模型、检索与安全能力。</p>

      <div className="mt-7 min-w-0 overflow-hidden rounded-lg border border-border bg-surface shadow-panel">
          <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border bg-bg px-5 py-5">
            <div className="flex items-start gap-3.5">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-fg text-surface">
                <ActiveIcon className="h-5 w-5" strokeWidth={1.7} />
              </span>
              <div>
                <h2 className="text-[18px] font-semibold leading-6">{activeDefinition.title}</h2>
                <p className="mt-1 text-caption text-muted">{activeDefinition.description}</p>
              </div>
            </div>
          </header>

          {activeModule === 'security' && <SecurityPolicySkeleton mode={securityMode} loading={securityLoading} onModeChange={(mode) => void updateSecurityMode(mode)} tab={securityTab} onTabChange={changeSecurityTab} />}

          {activeModule === 'models' && <section>
            <div className="flex justify-end border-b border-border px-[17px] py-3">
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
          </section>}

          {activeModule === 'retrieval' && <RetrievalSection />}

          {activeModule === 'events' && (() => {
            const pageSize = 20
            const pageCount = Math.max(1, Math.ceil(events.length / pageSize))
            const currentPage = Math.min(eventPage, pageCount)
            const pageEvents = events.slice((currentPage - 1) * pageSize, currentPage * pageSize)
            return <section>
              <div className="flex items-center justify-between border-b border-border px-[17px] py-3">
                <span className="text-meta text-muted">共 {events.length} 条</span>
                <Button
                  variant="compact"
                  size="icon"
                  onClick={() => void loadEvents()}
                  disabled={eventsLoading}
                  aria-label="刷新安全事件"
                  title="刷新"
                >
                  <RefreshCw className={cn('h-4 w-4', eventsLoading && 'animate-spin')} />
                </Button>
              </div>
              {eventsLoading && events.length === 0 ? (
                <div className="px-[17px] py-8 text-center text-caption text-muted">正在加载安全事件…</div>
              ) : events.length === 0 ? (
                <div className="px-[17px] py-8 text-center text-caption text-muted">暂无安全事件</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-caption">
                    <thead className="bg-bg text-meta text-muted">
                      <tr>
                        <th scope="col" className="w-[170px] px-[17px] py-2.5 font-medium">时间</th>
                        <th scope="col" className="w-[150px] px-3 py-2.5 font-medium">类型</th>
                        <th scope="col" className="px-3 py-2.5 font-medium">详情</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageEvents.map((event) => (
                        <tr key={event.id} className="border-t border-border align-top">
                          <td className="whitespace-nowrap px-[17px] py-3 font-mono text-meta text-muted"><time dateTime={event.created_at}>{fmtTime(event.created_at)}</time></td>
                          <td className="px-3 py-3"><Badge variant="muted">{event.kind}</Badge></td>
                          <td className="break-words px-3 py-3 text-fg">{event.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {events.length > 0 && <div className="flex items-center justify-between border-t border-border px-[17px] py-3">
                <span className="text-meta text-muted">第 {currentPage} / {pageCount} 页</span>
                <div className="flex items-center gap-1.5">
                  <Button variant="compact" size="icon" onClick={() => setEventPage((page) => Math.max(1, page - 1))} disabled={currentPage === 1} aria-label="上一页"><ChevronLeft /></Button>
                  <Button variant="compact" size="icon" onClick={() => setEventPage((page) => Math.min(pageCount, page + 1))} disabled={currentPage === pageCount} aria-label="下一页"><ChevronRight /></Button>
                </div>
              </div>}
            </section>
          })()}
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
