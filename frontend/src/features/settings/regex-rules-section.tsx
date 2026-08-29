import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ChevronLeft, ChevronRight, MoreHorizontal, Pencil, RotateCcw, Search } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { staggerTransition } from '@/components/layout'
import { api, errMsg } from '@/lib/api'
import type { DetectionRule } from '@/lib/types'

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

/** 正则规则表：CRUD、筛选与分页状态自持，网络请求归属本区块 */
export function RegexRulesSection() {
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
    <div className="border-b border-border px-cell py-4">
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
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-cell py-3">
      <span className="text-meta text-muted">共 {filtered.length} 条 · 每页 20 条</span>
      <div className="flex items-center gap-1.5"><span className="mr-1 font-mono text-meta text-muted">第 {currentPage} / {pageCount} 页</span><Button variant="compact" size="icon" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={currentPage === 1} aria-label="上一页"><ChevronLeft className="h-4 w-4" /></Button><Button variant="compact" size="icon" onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={currentPage === pageCount} aria-label="下一页"><ChevronRight className="h-4 w-4" /></Button></div>
    </div>
    {showAddForm && <div className="border-t border-border px-cell py-4"><div className="mb-2.5 flex flex-wrap items-center justify-between gap-2"><h3 className="text-panel font-semibold">新增自定义规则</h3><span className="text-meta text-muted">不限条数 · 模式最多 300 字符</span></div><div className="grid gap-2 sm:grid-cols-2"><Input placeholder="规则名称，如 employee_id" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><Input placeholder="正则匹配模式" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} /><Select value={form.kind} onValueChange={(kind) => setForm({ ...form, kind })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pii">个人信息（PII）</SelectItem><SelectItem value="credential">凭证</SelectItem><SelectItem value="unknown_suspect">疑似敏感信息</SelectItem></SelectContent></Select><Select value={form.validator || 'none'} onValueChange={(validator) => setForm({ ...form, validator: validator === 'none' ? '' : validator })}><SelectTrigger><SelectValue placeholder="校验函数（可选）" /></SelectTrigger><SelectContent><SelectItem value="none">不使用校验函数</SelectItem>{validators.map((validator) => <SelectItem key={validator} value={validator}>{VALIDATOR_LABELS[validator] ?? validator}</SelectItem>)}</SelectContent></Select></div><div className="mt-2.5 flex items-center gap-2.5"><Button variant="primary" size="sm" disabled={saving} onClick={() => void add()}>{saving ? '新增中…' : '新增规则'}</Button>{error && <p className="text-caption text-danger">{error}</p>}</div></div>}
  </section>
}
