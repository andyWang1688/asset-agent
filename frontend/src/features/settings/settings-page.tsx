import { useCallback, useEffect, useState, type ComponentType } from 'react'
import { Bot, Search, ScanSearch, ShieldCheck, Siren } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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
import type { DetectionRule, ModelRow, SecurityEvent, SettingsStatus } from '@/lib/types'
import { ModelSheet } from './model-sheet'
import { RetrievalSection } from './retrieval-section'
import { settingsModuleFromLocation, setSettingsModuleUrl, type SettingsModule } from './settings-navigation'

const KIND_LABELS: Record<string, string> = {
  credential: '凭证',
  pii: '个人信息（PII）',
  unknown_suspect: '疑似敏感信息',
}

const VALIDATOR_LABELS: Record<string, string> = {
  id_card: '身份证校验',
  luhn: 'Luhn 校验',
}

const SOURCE_LABELS: Record<string, string> = { builtin: '内置', override: '已覆盖', custom: '自定义' }

type ModuleStatus = { tone: 'ok' | 'warn' | 'err' | 'unknown'; label: string }

const MODULES: { id: SettingsModule; title: string; description: string; icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { id: 'models', title: '模型配置', description: '管理知识库与安全增强模型', icon: Bot },
  { id: 'retrieval', title: '检索配置', description: '配置语义召回与重排模型', icon: Search },
  { id: 'rules', title: '检测规则', description: '启停敏感信息检测规则', icon: ScanSearch },
  { id: 'policy', title: '安全策略', description: '编辑高级安全策略', icon: ShieldCheck },
  { id: 'events', title: '安全事件', description: '查看检测与处理记录', icon: Siren },
]

function statusFor(module: SettingsModule, status: SettingsStatus | null): ModuleStatus {
  if (!status) return { tone: 'unknown', label: '状态未知' }
  if (module === 'models' && !status.knowledge_model) return { tone: 'err', label: '知识库模型未配置' }
  if (module === 'retrieval' && status.retrieval_degraded) return { tone: 'warn', label: '检索降级' }
  if (module === 'retrieval' && !status.retrieval_checked) return { tone: 'unknown', label: '尚无运行记录' }
  if (module === 'rules' && status.rules_total > 0 && status.rules_enabled === 0) return { tone: 'warn', label: '规则全停用' }
  if (module === 'policy' && !status.policy_valid) return { tone: 'err', label: '策略无效' }
  if (module === 'events' && status.pending_security_events > 0) return { tone: 'err', label: `${status.pending_security_events} 项待处理` }
  return { tone: 'ok', label: '正常' }
}

const STATUS_CLASSES: Record<ModuleStatus['tone'], string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  err: 'bg-danger',
  unknown: 'bg-border-strong',
}

/** 去掉后端表单错误的字段路径前缀（detection.extra_rules[0].），保留友好信息 */
const friendlyRuleError = (msg: string) => msg
  .replace(/^detection\.extra_rules\[\d+\]\./, '')
  .replace(/^detection\.builtin_rules\.overrides\.[^.]+\./, '')

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

function RuleRow({
  rule,
  onToggle,
  onOverride,
  onRestore,
}: {
  rule: DetectionRule
  onToggle: () => void
  onOverride: (body: { pattern?: string; kind?: string }) => Promise<void>
  onRestore: () => Promise<void>
}) {
  const [advanced, setAdvanced] = useState(false)
  const [editing, setEditing] = useState(false)
  const [pattern, setPattern] = useState(rule.pattern || '')
  const [kind, setKind] = useState(rule.kind)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    setPattern(rule.pattern || '')
    setKind(rule.kind)
  }, [rule.pattern, rule.kind])
  const save = async () => {
    if (!pattern.trim() && kind === rule.kind) return
    setError('')
    setSaving(true)
    try {
      await onOverride({ pattern: pattern.trim() || undefined, kind: kind !== rule.kind ? kind : undefined })
      setEditing(false)
    } catch (e) {
      setError(friendlyRuleError(errMsg(e)))
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="border-b border-border px-3 py-3 last:border-b-0">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-caption font-medium">{rule.name}</strong>
            <Badge variant={rule.source === 'custom' ? 'muted' : rule.source === 'override' ? 'warn' : 'accent'}>
              {SOURCE_LABELS[rule.source || 'builtin']}
            </Badge>
            <Badge variant="muted">{KIND_LABELS[rule.kind] ?? rule.kind}</Badge>
          </div>
          <p className="mt-1 text-caption text-muted">{rule.description || '自定义匹配规则'}</p>
          {!!rule.examples?.length && <p className="mt-1 text-meta text-muted">示例命中：{rule.examples.join('、')}</p>}
          <Collapsible open={advanced} onOpenChange={setAdvanced}>
            <CollapsibleTrigger asChild>
              <button type="button" className="mt-1 text-meta text-primary hover:underline">{advanced ? '收起高级' : '展开高级（正则）'}</button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <code className="mt-1 block break-all rounded bg-bg px-2 py-1 font-mono text-meta text-muted">{rule.pattern || '未提供'}</code>
            </CollapsibleContent>
          </Collapsible>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1">
          <span className="text-meta text-muted">{rule.enabled ? '已启用' : '已停用'}</span>
          <Switch checked={rule.enabled} onCheckedChange={onToggle} aria-label={`切换 ${rule.name}`} />
        </div>
      </div>
      {rule.source !== 'custom' && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {editing ? (
            <div className="grid w-full gap-2 sm:grid-cols-[minmax(0,1fr)_170px_auto_auto]">
              <Input aria-label={`${rule.name} 正则`} value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="覆盖正则模式" />
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger aria-label={`${rule.name} 类别`}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="pii">个人信息（PII）</SelectItem>
                  <SelectItem value="credential">凭证</SelectItem>
                  <SelectItem value="unknown_suspect">疑似敏感信息</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="primary" size="sm" disabled={saving} onClick={() => void save()}>{saving ? '保存中…' : '保存覆盖'}</Button>
              <Button variant="compact" size="sm" onClick={() => setEditing(false)}>取消</Button>
            </div>
          ) : (
            <>
              <Button variant="compact" size="sm" onClick={() => setEditing(true)}>覆盖修改</Button>
              {rule.source === 'override' && <Button variant="compact" size="sm" onClick={() => void onRestore()}>恢复默认</Button>}
            </>
          )}
        </div>
      )}
      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
    </div>
  )
}

export function SettingsPage() {
  const { tab, refreshHealth } = useApp()
  const models = useModels()
  const [activeModule, setActiveModule] = useState<SettingsModule>(() => settingsModuleFromLocation(window.location))
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatus | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetRole, setSheetRole] = useState('knowledge')
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [deleting, setDeleting] = useState<ModelRow | null>(null)
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [rules, setRules] = useState<DetectionRule[]>([])
  const [validators, setValidators] = useState<string[]>([])
  const [ruleForm, setRuleForm] = useState({ name: '', pattern: '', kind: 'pii', validator: '' })
  const [ruleError, setRuleError] = useState('')
  const [ruleSaving, setRuleSaving] = useState(false)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [policyYaml, setPolicyYaml] = useState('')
  const [policyLoaded, setPolicyLoaded] = useState(false)
  const [policySaving, setPolicySaving] = useState(false)
  const [policyError, setPolicyError] = useState('')

  const loadStatus = useCallback(() => {
    void api.settingsStatus().then(setSettingsStatus).catch(() => setSettingsStatus(null))
  }, [])

  useEffect(() => {
    const onRouteChange = () => setActiveModule(settingsModuleFromLocation(window.location))
    window.addEventListener('popstate', onRouteChange)
    window.addEventListener('hashchange', onRouteChange)
    return () => {
      window.removeEventListener('popstate', onRouteChange)
      window.removeEventListener('hashchange', onRouteChange)
    }
  }, [loadStatus])

  useEffect(() => {
    if (tab !== 'settings') return
    setActiveModule(settingsModuleFromLocation(window.location))
    loadStatus()
  }, [loadStatus, tab])

  const selectModule = (module: SettingsModule) => {
    setActiveModule(module)
    setSettingsModuleUrl(module)
  }

  const loadEvents = () => {
    void api.securityEvents().then(setEvents).catch(() => setEvents([]))
  }
  useEffect(() => {
    loadEvents()
    void api.policyRules().then((result) => {
      setRules(result.rules)
      setValidators(result.validators)
    }).catch(() => setRuleError('规则加载失败'))
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

  const toggleRule = async (rule: DetectionRule) => {
    try {
      const result = rule.source === 'custom'
        ? await api.setCustomRule(rule.name, !rule.enabled)
        : await api.setBuiltinRule(rule.name, !rule.enabled)
      setRules((rows) => rows.map((r) => (r.name === rule.name ? { ...r, ...result.rule } : r)))
      toast.success(result.rule.enabled ? '规则已启用' : '规则已停用')
      loadStatus()
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  const overrideRule = async (rule: DetectionRule, body: { pattern?: string; kind?: string }) => {
    const result = await api.setBuiltinOverride(rule.name, body)
    setRules((rows) => rows.map((r) => (r.name === rule.name ? result.rule : r)))
    toast.success('内置规则覆盖已生效')
    loadStatus()
  }

  const restoreRule = async (rule: DetectionRule) => {
    try {
      const result = await api.restoreBuiltinOverride(rule.name)
      setRules((rows) => rows.map((r) => (r.name === rule.name ? result.rule : r)))
      toast.success('已恢复默认规则')
      loadStatus()
    } catch (e) {
      toast.error(errMsg(e))
    }
  }

  const addRule = async () => {
    setRuleError('')
    if (!/^[a-z0-9_]{1,40}$/.test(ruleForm.name)) return setRuleError('名称须为 1–40 位小写字母、数字或下划线')
    if (!ruleForm.pattern.trim()) return setRuleError('请输入匹配模式')
    if (ruleForm.pattern.length > 300) return setRuleError('匹配模式长度不得超过 300 个字符')
    setRuleSaving(true)
    try {
      const result = await api.addCustomRule({ ...ruleForm, validator: ruleForm.validator || undefined })
      setRules((rows) => [...rows, { ...result.rule, source: 'custom' }])
      setRuleForm({ name: '', pattern: '', kind: 'pii', validator: '' })
      toast.success('自定义规则已新增')
      loadStatus()
    } catch (e) {
      setRuleError(friendlyRuleError(errMsg(e)))
    } finally {
      setRuleSaving(false)
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
        loadStatus()
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
  const activeStatus = statusFor(activeModule, settingsStatus)
  const ActiveIcon = activeDefinition.icon

  return (
    <>
      <h1 className="page-heading">设置中心</h1>
      <p className="page-sub">管理模型、检索与安全能力。左侧状态来自当前运行接口，不以配置外观代替真实状态。</p>

      <div className="mt-7 grid items-start gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="设置模块" className="grid gap-1 rounded-lg border border-border bg-surface p-2 shadow-panel lg:sticky lg:top-[78px]">
          {MODULES.map((module) => {
            const Icon = module.icon
            const moduleStatus = statusFor(module.id, settingsStatus)
            return (
              <button
                key={module.id}
                type="button"
                aria-current={activeModule === module.id ? 'page' : undefined}
                onClick={() => selectModule(module.id)}
                className={cn(
                  'grid grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-2 py-2.5 text-left transition-colors',
                  activeModule === module.id ? 'bg-soft text-fg' : 'text-muted hover:bg-soft hover:text-fg',
                )}
              >
                <span className="grid h-8 w-8 place-items-center rounded-md border border-border bg-bg">
                  <Icon className="h-4 w-4" strokeWidth={1.7} />
                </span>
                <span className="min-w-0">
                  <strong className="block text-panel font-semibold">{module.title}</strong>
                  <span className="block truncate text-meta">{moduleStatus.label}</span>
                </span>
                <span className={cn('h-2 w-2 rounded-pill', STATUS_CLASSES[moduleStatus.tone])} aria-hidden="true" />
              </button>
            )
          })}
        </nav>

        <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-surface shadow-panel">
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
            <Badge variant={activeStatus.tone === 'err' ? 'err' : activeStatus.tone === 'warn' ? 'warn' : activeStatus.tone === 'ok' ? 'ok' : 'muted'}>
              {activeStatus.label}
            </Badge>
          </header>

          {activeModule === 'rules' && <section>
            <div className="border-b border-border px-[17px] py-4">
              <div className="mb-2.5 flex items-center justify-between"><h3 className="text-panel font-semibold">检测规则</h3><span className="text-meta text-muted">统一列表 · 最多 20 条自定义规则</span></div>
              <div className="divide-y divide-border rounded-md border border-border">
                {rules.map((rule) => <RuleRow key={rule.name} rule={rule} onToggle={() => void toggleRule(rule)} onOverride={(body) => overrideRule(rule, body)} onRestore={() => restoreRule(rule)} />)}
                {rules.length === 0 && <p className="px-3 py-4 text-caption text-muted">暂无检测规则</p>}
              </div>
            </div>
            <div className="border-b border-border px-[17px] py-4">
              <div className="mb-2.5 flex items-center justify-between"><h3 className="text-panel font-semibold">新增自定义规则</h3><span className="text-meta text-muted">模式最多 300 字符</span></div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input placeholder="规则名称，如 employee_id" value={ruleForm.name} onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })} />
                <Input placeholder="正则匹配模式" value={ruleForm.pattern} onChange={(e) => setRuleForm({ ...ruleForm, pattern: e.target.value })} />
                <Select value={ruleForm.kind} onValueChange={(kind) => setRuleForm({ ...ruleForm, kind })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pii">个人信息（PII）</SelectItem><SelectItem value="credential">凭证</SelectItem><SelectItem value="unknown_suspect">疑似敏感信息</SelectItem></SelectContent></Select>
                <Select value={ruleForm.validator || 'none'} onValueChange={(validator) => setRuleForm({ ...ruleForm, validator: validator === 'none' ? '' : validator })}><SelectTrigger><SelectValue placeholder="校验函数（可选）" /></SelectTrigger><SelectContent><SelectItem value="none">不使用校验函数</SelectItem>{validators.map((v) => <SelectItem key={v} value={v}>{VALIDATOR_LABELS[v] ?? v}</SelectItem>)}</SelectContent></Select>
              </div>
              <div className="mt-2.5 flex items-center gap-2.5"><Button variant="primary" size="sm" disabled={ruleSaving} onClick={() => void addRule()}>{ruleSaving ? '新增中…' : '新增规则'}</Button>{ruleError && <p className="text-caption text-danger">{ruleError}</p>}</div>
            </div>
          </section>}

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

          {activeModule === 'retrieval' && <RetrievalSection onStatusChange={loadStatus} />}

          {activeModule === 'policy' && <section>
            <div className="flex justify-end border-b border-border px-[17px] py-3">
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
          </section>}


          {activeModule === 'events' && <section>
            <div className="flex justify-end border-b border-border px-[17px] py-3">
              <Button variant="compact" size="sm" onClick={() => { loadEvents(); loadStatus() }}>
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
          </section>}
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
          loadStatus()
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
                    loadStatus()
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
