import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { api, errMsg } from '@/lib/api'
import type { EntropySensitivity, SecurityMode, SecuritySettingsView } from '@/lib/types'
import { RegexRulesSection } from './regex-rules-section'
import { SettingsGroup, SettingsRow } from './settings-ui'

const MODES: { value: SecurityMode; label: string; description: string }[] = [
  { value: 'default', label: '默认模式', description: '扫描后按既定规则自动处理，无需人工步骤。' },
  { value: 'confirm', label: '确认模式', description: '每份资料入库前先过确认页，逐份看一眼。' },
]

/** 安全策略：处理方式与基础检测；模型统一在模型配置管理。 */
export function SecurityPolicySection() {
  const [settings, setSettings] = useState<SecuritySettingsView | null>(null)
  const [keyword, setKeyword] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { void api.securitySettings().then(setSettings).catch(() => {}) }, [])
  const update = async (patch: Partial<SecuritySettingsView>) => {
    setSaving(true); setError('')
    try { setSettings(await api.updateSecuritySettings(patch)) }
    catch (e) { setError(errMsg(e)) }
    finally { setSaving(false) }
  }
  const mode = settings?.mode ?? 'default'
  /** 处理方式：乐观更新 + 失败回滚，沿用旧语义 */
  const changeMode = async (next: SecurityMode) => {
    const previous = settings
    setSettings((s) => (s ? { ...s, mode: next } : s))
    setSaving(true)
    try {
      setSettings(await api.updateSecuritySettings({ mode: next }))
      toast.success('处理方式已更新')
    } catch (e) {
      setSettings(previous)
      toast.error('处理方式更新失败：' + errMsg(e))
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
  const sensitivity = settings?.entropy.sensitivity === 'custom' ? '' : (settings?.entropy.sensitivity ?? 'balanced')
  const controlsDisabled = !settings || saving

  return (
    <div className="flex flex-col gap-4">
      <SettingsGroup title="处理方式" description="确认模式下每份资料入库前都需要人工确认。">
        {MODES.map(({ value, label, description }) => (
          <label
            key={value}
            className="flex cursor-pointer items-start gap-3 border-b px-4 py-3 last:border-b-0 hover:bg-accent/40"
          >
            <input
              type="radio"
              name="security-mode"
              value={value}
              checked={mode === value}
              disabled={controlsDisabled}
              onChange={() => void changeMode(value)}
              className="mt-1 accent-emerald-600"
            />
            <span>
              <span className="block text-sm font-medium">{label}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{description}</span>
            </span>
          </label>
        ))}
      </SettingsGroup>

      <SettingsGroup title="基础检测" description="本地正则与熵值检测，默认全部启用。">
        <SettingsRow
          label="关键词联想"
          description="根据关键词周边内容辅助识别敏感信息。"
          control={
            <Switch
              checked={settings?.keywords.enabled ?? true}
              disabled={controlsDisabled}
              onCheckedChange={(enabled) => void update({ keywords: { enabled, items: keywords } })}
              className="data-[state=checked]:bg-emerald-600"
              aria-label="启用关键词联想"
            />
          }
        />
        <SettingsRow
          label="乱串检测"
          description="识别看起来像随机密钥的文本片段。"
          control={
            <Switch
              checked={settings?.entropy.enabled ?? true}
              disabled={controlsDisabled}
              onCheckedChange={(enabled) => void update({ entropy: { enabled, sensitivity: settings?.entropy.sensitivity === 'custom' ? 'balanced' : (settings?.entropy.sensitivity ?? 'balanced') } })}
              className="data-[state=checked]:bg-emerald-600"
              aria-label="启用乱串检测"
            />
          }
        />
        <SettingsRow
          label="乱串灵敏度"
          description="越高越容易发现短串，也可能带来更多待确认项。"
          control={
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={sensitivity}
              onValueChange={(value) => {
                if (value) updateEntropy(value as Exclude<EntropySensitivity, 'custom'>)
              }}
              disabled={controlsDisabled}
              aria-label="乱串灵敏度"
            >
              <ToggleGroupItem value="sensitive" className="data-[state=on]:bg-emerald-600 data-[state=on]:text-white">敏感</ToggleGroupItem>
              <ToggleGroupItem value="balanced" className="data-[state=on]:bg-emerald-600 data-[state=on]:text-white">平衡</ToggleGroupItem>
              <ToggleGroupItem value="conservative" className="data-[state=on]:bg-emerald-600 data-[state=on]:text-white">保守</ToggleGroupItem>
            </ToggleGroup>
          }
        />
        <div className="border-b px-4 py-3 last:border-b-0">
          <p className="text-sm font-medium">关键词词条</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">命中词条时，周边内容会被辅助识别。</p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            {keywords.length === 0 ? (
              <span className="text-xs text-muted-foreground">暂无词条</span>
            ) : (
              keywords.map((item) => (
                <span key={item} className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs">
                  {item}
                  <button
                    type="button"
                    className="text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => removeKeyword(item)}
                    aria-label={`删除关键词 ${item}`}
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))
            )}
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Input
              className="w-full sm:w-64"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword() } }}
              placeholder="添加关键词"
              disabled={controlsDisabled}
              aria-label="添加关键词"
            />
            <Button
              className="bg-emerald-600 text-white hover:bg-emerald-700"
              size="sm"
              onClick={addKeyword}
              disabled={!keyword.trim() || controlsDisabled}
            >
              添加
            </Button>
          </div>
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </div>
      </SettingsGroup>

      <RegexRulesSection />
    </div>
  )
}
