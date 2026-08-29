import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { fadeTransition, stateTransition } from '@/components/layout'
import { api, errMsg } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { EntropySensitivity, ModelRow, SecurityMode, SecuritySettingsView } from '@/lib/types'
import { ModelCard, type ModelCardActions } from './model-card'
import { RegexRulesSection } from './regex-rules-section'
import { SECURITY_TABS, type SecurityTab } from './settings-navigation'

const ENTROPY_OPTIONS: { value: Exclude<EntropySensitivity, 'custom'>; label: string; description: string }[] = [
  { value: 'sensitive', label: '敏感', description: '更容易发现短小的乱串，可能带来更多待确认项。' },
  { value: 'balanced', label: '平衡（默认）', description: '在发现能力与误报之间保持平衡。' },
  { value: 'conservative', label: '保守', description: '减少误报，但可能漏过较短的敏感串。' },
]

/** 安全策略：处理方式 + 配置细则；settings 视图（含 mode）在此自加载与回滚 */
export function SecurityPolicySection({
  tab,
  onTabChange,
  securityModels,
  securityModelActions,
}: {
  tab: SecurityTab
  onTabChange: (tab: SecurityTab) => void
  securityModels: ModelRow[]
  securityModelActions: ModelCardActions
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
  const mode = settings?.mode ?? 'default'
  /** Processing mode: optimistic update + rollback on failure, same semantics as the old SettingsPage.updateSecurityMode */
  const changeMode = async (next: SecurityMode) => {
    const previous = settings
    setSettings((s) => (s ? { ...s, mode: next } : s))
    setSaving(true)
    try {
      setSettings(await api.updateSecuritySettings({ mode: next }))
      toast.success('Processing method has been updated')
    } catch (e) {
      setSettings(previous)
      toast.error('Failed to update processing method: ' + errMsg(e))
    } finally {
      setSaving(false)
    }
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
  const tabContent = tab === 'regex' ? <RegexRulesSection /> : tab === 'keywords' ? <section className="space-y-4 px-cell py-4">
    <div className="flex items-center justify-between"><div><h3 className="text-panel font-semibold">关键词联想</h3><p className="mt-1 text-caption text-muted">根据关键词周边内容辅助识别敏感信息。</p></div><Switch checked={settings?.keywords.enabled ?? true} disabled={!settings || saving} onCheckedChange={(enabled) => void update({ keywords: { enabled, items: keywords } })} aria-label="启用关键词联想" /></div>
    <div className="flex flex-wrap gap-2">{keywords.map((item) => <span key={item} className="inline-flex items-center gap-1 rounded-pill bg-soft px-2.5 py-1 text-caption">{item}<button type="button" className="text-muted hover:text-fg" onClick={() => removeKeyword(item)} aria-label={`删除关键词 ${item}`}>×</button></span>)}</div>
    <div className="flex gap-2"><Input value={keyword} onChange={(e) => setKeyword(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword() } }} placeholder="添加关键词" /><Button variant="compact" size="sm" onClick={addKeyword} disabled={!keyword.trim() || saving}>添加</Button></div>
    {error && <p className="text-caption text-danger">{error}</p>}
  </section> : tab === 'entropy' ? <section className="space-y-4 px-cell py-4">
    <div className="flex items-center justify-between"><div><h3 className="text-panel font-semibold">乱串检测</h3><p className="mt-1 text-caption text-muted">识别看起来像随机密钥的文本片段。</p></div><Switch checked={settings?.entropy.enabled ?? true} disabled={!settings || saving} onCheckedChange={(enabled) => void update({ entropy: { enabled, sensitivity: settings?.entropy.sensitivity === 'custom' ? 'balanced' : (settings?.entropy.sensitivity ?? 'balanced') } })} aria-label="启用乱串检测" /></div>
    <div className="grid gap-2 sm:grid-cols-3">{ENTROPY_OPTIONS.map((option) => <label key={option.value} className={cn('cursor-pointer rounded-md border px-3 py-2.5', settings?.entropy.sensitivity === option.value ? 'border-fg/45 bg-soft' : 'border-border')}><input type="radio" name="entropy-sensitivity" value={option.value} checked={settings?.entropy.sensitivity === option.value} disabled={!settings || saving} onChange={() => updateEntropy(option.value)} className="mr-2 accent-[var(--color-fg)]" /><strong className="text-caption font-semibold">{option.label}</strong><span className="mt-1 block text-meta text-muted">{option.description}</span></label>)}</div>
    {error && <p className="text-caption text-danger">{error}</p>}
  </section> : <section className="space-y-4 px-cell py-4">
    <div><h3 className="text-panel font-semibold">安全增强模型</h3><p className="mt-1 text-caption text-muted">可选的本地 AI 辅检，只加严不放松，仅允许本机或内网端点。</p></div>
    <AnimatePresence mode="popLayout">{securityModels.length === 0 ? <ModelCard key="empty" m={null} emptyDesc="未配置时，继续使用本地检测。" emptyChip="本地检测生效" {...securityModelActions} /> : securityModels.map((model, index) => <ModelCard key={model.id} index={index} m={model} emptyDesc="" {...securityModelActions} />)}</AnimatePresence>
  </section>
  return <section>
    <div className="border-b border-border px-cell py-4"><h3 className="text-panel font-semibold">处理方式</h3><div className="mt-3 grid gap-2 sm:grid-cols-2">{([['default', '默认模式', '扫描后按既定规则自动处理，无需人工步骤。'], ['confirm', '确认模式', '每份资料入库前先过确认页，逐份看一眼。']] as const).map(([value, label, description]) => <label key={value} className={cn('flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 transition-colors', mode === value ? 'border-fg/45 bg-soft' : 'border-border')}><input type="radio" name="security-mode" value={value} checked={mode === value} disabled={!settings || saving} onChange={() => void changeMode(value)} className="mt-1 accent-[var(--color-fg)]" /><span><strong className="block text-caption font-semibold">{label}</strong><span className="mt-0.5 block text-meta text-muted">{description}</span></span></label>)}</div></div>
    <div><div className="border-b border-border px-cell pt-3"><h3 className="mb-2.5 text-panel font-semibold">配置细则</h3><nav className="flex flex-wrap gap-1" aria-label="安全策略配置细则">{SECURITY_TABS.map(({ id, label }) => <button key={id} type="button" aria-current={tab === id ? 'page' : undefined} onClick={() => onTabChange(id)} className={cn('motion-interactive relative isolate rounded-t-md px-3 py-2 text-caption transition-colors', tab === id ? 'font-semibold text-fg' : 'text-muted hover:text-fg')}>{tab === id && <motion.span layoutId="security-tab-indicator" className="absolute inset-x-0 bottom-0 -z-0 h-0.5 bg-fg" transition={stateTransition(reduceMotion)} />}<span className="relative z-10">{label}</span></button>)}</nav></div><AnimatePresence mode="wait" initial={false}><motion.div key={tab} initial={reduceMotion ? false : { opacity: 0, x: 'var(--spacing-content)' }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'calc(-1 * var(--spacing-content))' }} transition={fadeTransition(reduceMotion)}>{tabContent}</motion.div></AnimatePresence></div>
  </section>
}
