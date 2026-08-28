import { useCallback, useEffect, useState, type ComponentType } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Bot, ChevronLeft, ChevronRight, MoreHorizontal, Pencil, RefreshCw, RotateCcw, Search, ShieldCheck, Siren } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState, fadeTransition, LoadingState, PageShell, SectionCard, staggerTransition, stateTransition } from '@/components/layout'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
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
import { useApp } from '@/store/app-state'
import { useModels } from '@/hooks/use-models'
import { api, errMsg } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DetectionRule, EntropySensitivity, ModelRow, SecurityEvent, SecurityMode, SecuritySettingsView } from '@/lib/types'
import { ModelSheet } from './model-sheet'
import { RetrievalSection } from './retrieval-section'
import type { SettingsModule } from './settings-navigation'

const MODULES: { id: SettingsModule; title: string; description: string; icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { id: 'models', title: '模型配置', description: '管理知识库模型', icon: Bot },
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
  index = 0,
}: {
  m: ModelRow | null
  emptyDesc: string
  emptyChip?: string
  onAdd: () => void
  onActivate: (id: number) => void
  onTest: (id: number) => Promise<unknown>
  onEdit: (m: ModelRow) => void
  onDelete: (m: ModelRow) => void
  index?: number
}) {
  const [testing, setTesting] = useState(false)
  const reduceMotion = useReducedMotion()
  return (
    <motion.div className="mb-2 last:mb-0" layout initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}>
    <div className="motion-card rounded-md border border-border bg-bg p-3">
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
    </motion.div>
  )
}

const KIND_LABELS: Record<string, string> = {
  credential: '凭证',
  pii: '个人信息（PII）',
  unknown_suspect: '疑似敏感信息',
}
const VALIDATOR_LABELS: Record<string, string> = { id_card: '身份证校验', luhn: 'Luhn 校验' }
const SOURCE_LABELS: Record<string, string> = { builtin: '内置', override: '已覆盖', custom: '自定义' }
const friendlyRuleError = (msg: string) => msg
  .replace(/^detection\.extra_rules\[\d+\]\./, '')
  .replace(/^detection\.builtin_rules\.overrides\.[^.]+\./, '')

function RuleRow({ rule, index, onToggle, onOverride, onRestore, onDelete }: {
  rule: DetectionRule
  index: number
  onToggle: () => void
  onOverride: (body: { pattern?: string; kind?: string }) => Promise<void>
  onRestore: () => Promise<void>
  onDelete: () => Promise<void>
}) {
  const [advanced, setAdvanced] = useState(false)
  const [editing, setEditing] = useState(false)
  const [pattern, setPattern] = useState(rule.pattern || '')
  const [kind, setKind] = useState(rule.kind)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const reduceMotion = useReducedMotion()
  useEffect(() => { setPattern(rule.pattern || ''); setKind(rule.kind) }, [rule.pattern, rule.kind])
  const save = async () => {
    if (!pattern.trim() && kind === rule.kind) return
    setError(''); setSaving(true)
    try {
      await onOverride({ pattern: pattern.trim() || undefined, kind: kind !== rule.kind ? kind : undefined })
      setEditing(false)
    } catch (e) { setError(friendlyRuleError(errMsg(e))) }
    finally { setSaving(false) }
  }
  return <>
    <motion.tr className="border-t border-border align-top text-caption first:border-t-0" layout initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}>
      <th scope="row" className="min-w-[170px] px-3 py-3 text-left font-medium">{rule.name}</th>
      <td className="whitespace-nowrap px-3 py-3"><Badge variant="muted">{KIND_LABELS[rule.kind] ?? rule.kind}</Badge></td>
      <td className="whitespace-nowrap px-3 py-3"><Badge variant={rule.source === 'custom' ? 'muted' : rule.source === 'override' ? 'warn' : 'accent'}>{SOURCE_LABELS[rule.source || 'builtin']}</Badge></td>
      <td className="min-w-[300px] max-w-[560px] px-3 py-3 text-muted">
        <p className="break-words">{rule.description || '自定义匹配规则'}</p>
        {!!rule.examples?.length && <p className="mt-1 text-meta">示例命中：{rule.examples.join('、')}</p>}
      </td>
      <td className="whitespace-nowrap px-3 py-3">
        <div className="flex items-center gap-2"><span className="text-meta text-muted">{rule.enabled ? '已启用' : '已停用'}</span><Switch checked={rule.enabled} onCheckedChange={onToggle} aria-label={`切换 ${rule.name}`} /></div>
      </td>
      <td className="whitespace-nowrap px-3 py-3">
        <div className="flex items-center gap-1">
          {rule.source !== 'custom' && <Button variant="compact" size="icon" onClick={() => setEditing(!editing)} aria-label={`覆盖修改 ${rule.name}`} title="覆盖修改"><Pencil className="h-3.5 w-3.5" /></Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="compact" size="icon" aria-label={`规则操作 ${rule.name}`} title="更多操作"><MoreHorizontal className="h-4 w-4" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[170px]">
              <DropdownMenuItem onSelect={() => setAdvanced((value) => !value)}>{advanced ? '收起正则' : '展开正则'}</DropdownMenuItem>
              {rule.source !== 'custom' && <DropdownMenuItem onSelect={() => setEditing(true)}><Pencil />覆盖修改</DropdownMenuItem>}
              {rule.source === 'override' && <DropdownMenuItem onSelect={() => void onRestore()}><RotateCcw />恢复默认</DropdownMenuItem>}
              {rule.source === 'custom' && <DropdownMenuItem onSelect={() => void onDelete()}>删除规则</DropdownMenuItem>}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </motion.tr>
    <AnimatePresence initial={false}>
    {advanced && <motion.tr initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="border-t border-border bg-bg"><td colSpan={6} className="px-3 py-2"><code className="block break-all font-mono text-meta text-muted">正则：{rule.pattern || '未提供'}</code></td></motion.tr>}
    {editing && rule.source !== 'custom' && <motion.tr initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="border-t border-border bg-bg"><td colSpan={6} className="px-3 py-3">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_170px_auto_auto]">
        <Input aria-label={`${rule.name} 正则`} value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="覆盖正则模式" />
        <Select value={kind} onValueChange={setKind}><SelectTrigger aria-label={`${rule.name} 类别`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pii">个人信息（PII）</SelectItem><SelectItem value="credential">凭证</SelectItem><SelectItem value="unknown_suspect">疑似敏感信息</SelectItem></SelectContent></Select>
        <Button variant="primary" size="sm" disabled={saving} onClick={() => void save()}>{saving ? '保存中…' : '保存覆盖'}</Button>
        <Button variant="compact" size="sm" onClick={() => setEditing(false)}>取消</Button>
      </div>
      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
    </td></motion.tr>}
    </AnimatePresence>
  </>
}

function RegexRulesSection() {
  const [rules, setRules] = useState<DetectionRule[]>([])
  const [validators, setValidators] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [form, setForm] = useState({ name: '', pattern: '', kind: 'pii', validator: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)
  const load = useCallback(async () => {
    try { const result = await api.policyRules(); setRules(result.rules); setValidators(result.validators) }
    catch { setError('规则加载失败') }
  }, [])
  useEffect(() => { void load() }, [load])
  const filtered = rules.filter((rule) => {
    const needle = query.trim().toLowerCase()
    const matchesQuery = !needle || `${rule.name} ${rule.description || ''} ${(rule.examples || []).join(' ')} ${rule.pattern || ''}`.toLowerCase().includes(needle)
    return matchesQuery && (kindFilter === 'all' || rule.kind === kindFilter)
  })
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20))
  const currentPage = Math.min(page, pageCount)
  const pageRules = filtered.slice((currentPage - 1) * 20, currentPage * 20)
  const toggle = async (rule: DetectionRule) => {
    try {
      const result = rule.source === 'custom' ? await api.setCustomRule(rule.name, !rule.enabled) : await api.setBuiltinRule(rule.name, !rule.enabled)
      setRules((rows) => rows.map((row) => row.name === rule.name ? { ...row, ...result.rule } : row))
      toast.success(result.rule.enabled ? '规则已启用' : '规则已停用')
    } catch (e) { toast.error(errMsg(e)) }
  }
  const override = async (rule: DetectionRule, body: { pattern?: string; kind?: string }) => {
    const result = await api.setBuiltinOverride(rule.name, body)
    setRules((rows) => rows.map((row) => row.name === rule.name ? result.rule : row))
    toast.success('内置规则覆盖已生效')
  }
  const restore = async (rule: DetectionRule) => {
    try { const result = await api.restoreBuiltinOverride(rule.name); setRules((rows) => rows.map((row) => row.name === rule.name ? result.rule : row)); toast.success('已恢复默认规则') }
    catch (e) { toast.error(errMsg(e)) }
  }
  const remove = async (rule: DetectionRule) => {
    try {
      await api.deleteCustomRule(rule.name)
      setRules((rows) => rows.filter((row) => row.name !== rule.name))
      toast.success('自定义规则已删除')
    } catch (e) { toast.error(errMsg(e)) }
  }
  const add = async () => {
    setError('')
    if (!/^[a-z0-9_]{1,40}$/.test(form.name)) return setError('名称须为 1–40 位小写字母、数字或下划线')
    if (!form.pattern.trim()) return setError('请输入匹配模式')
    if (form.pattern.length > 300) return setError('匹配模式长度不得超过 300 个字符')
    setSaving(true)
    try { const result = await api.addCustomRule({ ...form, validator: form.validator || undefined }); setRules((rows) => [...rows, { ...result.rule, source: 'custom' }]); setForm({ name: '', pattern: '', kind: 'pii', validator: '' }); toast.success('自定义规则已新增') }
    catch (e) { setError(friendlyRuleError(errMsg(e))) }
    finally { setSaving(false) }
  }
  return <section>
    <div className="border-b border-border px-[17px] py-4">
      <div className="mb-1"><h3 className="text-panel font-semibold">正则规则</h3><p className="mt-1 text-caption text-muted">匹配上以下任一规则的内容即视为敏感信息；可新增自定义规则，或覆盖/停用内置规则。</p></div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><Input className="pl-8" aria-label="搜索规则" placeholder="搜索规则名称、描述或示例" value={query} onChange={(e) => { setQuery(e.target.value); setPage(1) }} /></div>
        <Select value={kindFilter} onValueChange={(value) => { setKindFilter(value); setPage(1) }}><SelectTrigger className="w-[170px]" aria-label="按类型筛选"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部类型</SelectItem>{Object.entries(KIND_LABELS).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select>
        <Button variant="primary" size="sm" className="ml-auto" onClick={() => setShowAddForm((value) => !value)}>{showAddForm ? '收起新增' : '新增规则'}</Button>
      </div>
      {rules.length > 50 && <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-caption text-warn">规则较多可能影响扫描性能，建议定期清理不再使用的规则</p>}
    </div>
    <div className="overflow-x-auto">
      <table className="min-w-[940px] w-full border-collapse text-left">
        <thead className="bg-bg text-meta text-muted"><tr><th scope="col" className="px-3 py-2.5 font-medium">名称</th><th scope="col" className="px-3 py-2.5 font-medium">类型</th><th scope="col" className="px-3 py-2.5 font-medium">来源</th><th scope="col" className="px-3 py-2.5 font-medium">说明 / 示例命中</th><th scope="col" className="px-3 py-2.5 font-medium">状态</th><th scope="col" className="px-3 py-2.5 font-medium">操作</th></tr></thead>
        <tbody>
          <AnimatePresence initial={false}>
          {pageRules.map((rule, index) => <RuleRow key={rule.name} rule={rule} index={index} onToggle={() => void toggle(rule)} onOverride={(body) => override(rule, body)} onRestore={() => restore(rule)} onDelete={() => remove(rule)} />)}
          </AnimatePresence>
          {pageRules.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-caption text-muted">暂无匹配规则</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-[17px] py-3">
      <span className="text-meta text-muted">共 {filtered.length} 条 · 每页 20 条</span>
      <div className="flex items-center gap-1.5"><span className="mr-1 font-mono text-meta text-muted">第 {currentPage} / {pageCount} 页</span><Button variant="compact" size="icon" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={currentPage === 1} aria-label="上一页"><ChevronLeft className="h-4 w-4" /></Button><Button variant="compact" size="icon" onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={currentPage === pageCount} aria-label="下一页"><ChevronRight className="h-4 w-4" /></Button></div>
    </div>
    {showAddForm && <div className="border-t border-border px-[17px] py-4"><div className="mb-2.5 flex flex-wrap items-center justify-between gap-2"><h3 className="text-panel font-semibold">新增自定义规则</h3><span className="text-meta text-muted">不限条数 · 模式最多 300 字符</span></div><div className="grid gap-2 sm:grid-cols-2"><Input placeholder="规则名称，如 employee_id" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="正则匹配模式" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} /><Select value={form.kind} onValueChange={(kind) => setForm({ ...form, kind })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pii">个人信息（PII）</SelectItem><SelectItem value="credential">凭证</SelectItem><SelectItem value="unknown_suspect">疑似敏感信息</SelectItem></SelectContent></Select><Select value={form.validator || 'none'} onValueChange={(validator) => setForm({ ...form, validator: validator === 'none' ? '' : validator })}><SelectTrigger><SelectValue placeholder="校验函数（可选）" /></SelectTrigger><SelectContent><SelectItem value="none">不使用校验函数</SelectItem>{validators.map((validator) => <SelectItem key={validator} value={validator}>{VALIDATOR_LABELS[validator] ?? validator}</SelectItem>)}</SelectContent></Select></div><div className="mt-2.5 flex items-center gap-2.5"><Button variant="primary" size="sm" disabled={saving} onClick={() => void add()}>{saving ? '新增中…' : '新增规则'}</Button>{error && <p className="text-caption text-danger">{error}</p>}</div></div>}
  </section>
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

const ENTROPY_OPTIONS: { value: Exclude<EntropySensitivity, 'custom'>; label: string; description: string }[] = [
  { value: 'sensitive', label: '敏感', description: '更容易发现短小的乱串，可能带来更多待确认项。' },
  { value: 'balanced', label: '平衡（默认）', description: '在发现能力与误报之间保持平衡。' },
  { value: 'conservative', label: '保守', description: '减少误报，但可能漏过较短的敏感串。' },
]

type SecurityModelActions = {
  onAdd: () => void
  onActivate: (id: number) => void
  onTest: (id: number) => Promise<unknown>
  onEdit: (model: ModelRow) => void
  onDelete: (model: ModelRow) => void
}

function SecurityPolicySkeleton({
  mode,
  loading,
  onModeChange,
  tab,
  onTabChange,
  securityModels,
  securityModelActions,
}: {
  mode: SecurityMode
  loading: boolean
  onModeChange: (mode: SecurityMode) => void
  tab: SecurityTab
  onTabChange: (tab: SecurityTab) => void
  securityModels: ModelRow[]
  securityModelActions: SecurityModelActions
}) {
  const [settings, setSettings] = useState<SecuritySettingsView | null>(null)
  const [keyword, setKeyword] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const reduceMotion = useReducedMotion()
  useEffect(() => { void api.securitySettings().then(setSettings).catch(() => {}) }, [])
  const update = async (patch: Partial<SecuritySettingsView>) => {
    setSaving(true); setError('')
    try { setSettings(await api.updateSecuritySettings(patch)) }
    catch (e) { setError(errMsg(e)) }
    finally { setSaving(false) }
  }
  const keywords = settings?.keywords.items ?? []
  const addKeyword = () => {
    const value = keyword.trim()
    if (!value || keywords.includes(value)) return
    setKeyword('')
    void update({ keywords: { enabled: settings?.keywords.enabled ?? true, items: [...keywords, value] } })
  }
  const removeKeyword = (value: string) => {
    void update({ keywords: { enabled: settings?.keywords.enabled ?? true, items: keywords.filter((item) => item !== value) } })
  }
  const updateEntropy = (value: Exclude<EntropySensitivity, 'custom'>) => {
    void update({ entropy: { enabled: settings?.entropy.enabled ?? true, sensitivity: value } })
  }
  const tabContent = tab === 'regex' ? <RegexRulesSection /> : tab === 'keywords' ? <section className="space-y-4 px-[17px] py-4">
    <div className="flex items-center justify-between"><div><h3 className="text-panel font-semibold">关键词联想</h3><p className="mt-1 text-caption text-muted">根据关键词周边内容辅助识别敏感信息。</p></div><Switch checked={settings?.keywords.enabled ?? true} disabled={!settings || saving} onCheckedChange={(enabled) => void update({ keywords: { enabled, items: keywords } })} aria-label="启用关键词联想" /></div>
    <div className="flex flex-wrap gap-2">{keywords.map((item) => <span key={item} className="inline-flex items-center gap-1 rounded-pill bg-soft px-2.5 py-1 text-caption">{item}<button type="button" className="text-muted hover:text-fg" onClick={() => removeKeyword(item)} aria-label={`删除关键词 ${item}`}>×</button></span>)}</div>
    <div className="flex gap-2"><Input value={keyword} onChange={(e) => setKeyword(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword() } }} placeholder="添加关键词" /><Button variant="compact" size="sm" onClick={addKeyword} disabled={!keyword.trim() || saving}>添加</Button></div>
    {error && <p className="text-caption text-danger">{error}</p>}
  </section> : tab === 'entropy' ? <section className="space-y-4 px-[17px] py-4">
    <div className="flex items-center justify-between"><div><h3 className="text-panel font-semibold">乱串检测</h3><p className="mt-1 text-caption text-muted">识别看起来像随机密钥的文本片段。</p></div><Switch checked={settings?.entropy.enabled ?? true} disabled={!settings || saving} onCheckedChange={(enabled) => void update({ entropy: { enabled, sensitivity: settings?.entropy.sensitivity === 'custom' ? 'balanced' : (settings?.entropy.sensitivity ?? 'balanced') } })} aria-label="启用乱串检测" /></div>
    <div className="grid gap-2 sm:grid-cols-3">{ENTROPY_OPTIONS.map((option) => <label key={option.value} className={cn('cursor-pointer rounded-md border px-3 py-2.5', settings?.entropy.sensitivity === option.value ? 'border-fg/45 bg-soft' : 'border-border')}><input type="radio" name="entropy-sensitivity" value={option.value} checked={settings?.entropy.sensitivity === option.value} disabled={!settings || saving} onChange={() => updateEntropy(option.value)} className="mr-2 accent-[var(--color-fg)]" /><strong className="text-caption font-semibold">{option.label}</strong><span className="mt-1 block text-meta text-muted">{option.description}</span></label>)}</div>
    {error && <p className="text-caption text-danger">{error}</p>}
  </section> : <section className="space-y-4 px-[17px] py-4">
    <div><h3 className="text-panel font-semibold">安全增强模型</h3><p className="mt-1 text-caption text-muted">可选的本地 AI 辅检，只加严不放松，仅允许本机或内网端点。</p></div>
    <AnimatePresence mode="popLayout">{securityModels.length === 0 ? <ModelCard key="empty" m={null} emptyDesc="未配置时，继续使用本地检测。" emptyChip="本地检测生效" {...securityModelActions} /> : securityModels.map((model, index) => <ModelCard key={model.id} index={index} m={model} emptyDesc="" {...securityModelActions} />)}</AnimatePresence>
  </section>
  return <section>
    <div className="border-b border-border px-[17px] py-4"><h3 className="text-panel font-semibold">处理方式</h3><div className="mt-3 grid gap-2 sm:grid-cols-2">{([['default', '默认模式', '扫描后按既定规则自动处理，无需人工步骤。'], ['confirm', '确认模式', '每份资料入库前先过确认页，逐份看一眼。']] as const).map(([value, label, description]) => <label key={value} className={cn('flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 transition-colors', mode === value ? 'border-fg/45 bg-soft' : 'border-border')}><input type="radio" name="security-mode" value={value} checked={mode === value} disabled={loading} onChange={() => onModeChange(value)} className="mt-1 accent-[var(--color-fg)]" /><span><strong className="block text-caption font-semibold">{label}</strong><span className="mt-0.5 block text-meta text-muted">{description}</span></span></label>)}</div></div>
    <div><div className="border-b border-border px-[17px] pt-3"><h3 className="mb-2.5 text-panel font-semibold">配置细则</h3><nav className="flex flex-wrap gap-1" aria-label="安全策略配置细则">{SECURITY_TABS.map(({ id, label }) => <button key={id} type="button" aria-current={tab === id ? 'page' : undefined} onClick={() => onTabChange(id)} className={cn('motion-interactive relative isolate rounded-t-md px-3 py-2 text-caption transition-colors', tab === id ? 'font-semibold text-fg' : 'text-muted hover:text-fg')}>{tab === id && <motion.span layoutId="security-tab-indicator" className="absolute inset-x-0 bottom-0 -z-0 h-0.5 bg-fg" transition={stateTransition(reduceMotion)} />}<span className="relative z-10">{label}</span></button>)}</nav></div><AnimatePresence mode="wait" initial={false}><motion.div key={tab} initial={reduceMotion ? false : { opacity: 0, x: 'var(--spacing-content)' }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'calc(-1 * var(--spacing-content))' }} transition={fadeTransition(reduceMotion)}>{tabContent}</motion.div></AnimatePresence></div>
  </section>
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
  const [eventsClearing, setEventsClearing] = useState(false)
  const [eventPage, setEventPage] = useState(1)
  const [securityMode, setSecurityMode] = useState<SecurityMode>('default')
  const [securityLoading, setSecurityLoading] = useState(false)
  const [securityTab, setSecurityTab] = useState<SecurityTab>(securityTabFromHash)
  const reduceMotion = useReducedMotion()

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
    <PageShell title="设置中心" description="管理模型、检索与安全能力。">
      <SectionCard className="min-w-0 overflow-hidden" contentClassName="p-0">
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

          {activeModule === 'security' && <SecurityPolicySkeleton mode={securityMode} loading={securityLoading} onModeChange={(mode) => void updateSecurityMode(mode)} tab={securityTab} onTabChange={changeSecurityTab} securityModels={models.security} securityModelActions={groupProps('security')} />}

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
                <AnimatePresence mode="popLayout">{models.knowledge.map((m, index) => <ModelCard key={m.id} index={index} m={m} emptyDesc="" {...groupProps('knowledge')} />)}</AnimatePresence>
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
                <div className="flex items-center gap-compact">
                  {events.length > 0 && <Button variant="danger" size="sm" onClick={() => void api.clearSecurityEvents().then(() => { setEventsClearing(true); setEvents([]); toast.success('安全事件已清空') }).catch((e) => toast.error(errMsg(e)))}>清空</Button>}
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
              </div>
              {eventsLoading && events.length === 0 ? (
                <LoadingState label="正在加载安全事件…" />
              ) : events.length === 0 && !eventsClearing ? (
                <EmptyState title="暂无安全事件" />
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
                    <tbody><AnimatePresence initial={false} onExitComplete={() => setEventsClearing(false)}>
                      {pageEvents.map((event, index) => (
                        <motion.tr key={event.id} className="border-t border-border align-top" initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={staggerTransition(reduceMotion, index)}>
                          <td className="whitespace-nowrap px-[17px] py-3 font-mono text-meta text-muted"><time dateTime={event.created_at}>{fmtTime(event.created_at)}</time></td>
                          <td className="px-3 py-3"><Badge variant="muted">{event.kind}</Badge></td>
                          <td className="break-words px-3 py-3 text-fg">{event.detail}</td>
                        </motion.tr>
                      ))}
                    </AnimatePresence></tbody>
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
