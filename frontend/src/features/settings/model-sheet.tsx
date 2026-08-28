import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@radix-ui/react-label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { FormRow } from '@/components/layout'
import { errMsg } from '@/lib/api'
import type { ModelBody, ModelRow, Preset } from '@/lib/types'

const ROLE_HINTS: Record<string, string> = {
  knowledge: '必配：统一负责 Wiki 编译与知识问答，未配置时提交与问答被禁用。每个角色只能激活一个。',
  security: '可选增强检测：接入本地检测之后，只能新增或加严识别结果，失败自动回退本地检测。默认仅允许 localhost/内网端点。',
}

interface ModelSheetProps {
  open: boolean
  role: string
  model: ModelRow | null
  presets: Preset[]
  onSave: (body: ModelBody) => Promise<void>
  onClose: () => void
}

/** 模型编辑 Sheet：角色 / 名称 / Provider / API 地址 / 模型名 / API Key / 激活 */
export function ModelSheet({ open, role, model, presets, onSave, onClose }: ModelSheetProps) {
  const [name, setName] = useState('')
  const [presetType, setPresetType] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelName, setModelName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [active, setActive] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(model?.name ?? '')
    setPresetType(model?.provider_type || (presets[0]?.type ?? ''))
    setBaseUrl(model?.base_url || presets[0]?.base_url || '')
    setModelName(model?.model || presets[0]?.model || '')
    setApiKey('')
    setActive(model ? model.is_active : true)
    setError('')
  }, [open, model, presets])

  const submit = async () => {
    if (!name.trim()) {
      setError('请填写名称')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave({
        id: model?.id ?? null,
        name: name.trim(),
        provider_type: presetType,
        base_url: baseUrl.trim(),
        model: modelName.trim(),
        api_key: apiKey.trim(),
        is_active: active,
        role,
      } as ModelBody)
      onClose()
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent className="w-[440px] max-w-full">
        <SheetHeader>
          <SheetTitle>{model ? '编辑模型' : '添加模型'}</SheetTitle>
        </SheetHeader>
        <div className="flex-1 space-y-3.5 overflow-y-auto px-5 py-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted">角色</Label>
            <Select value={role} disabled>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="knowledge">知识库（必配）</SelectItem>
                <SelectItem value="security">安全增强（可选）</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted">{ROLE_HINTS[role] || ''}</p>
          </div>
          <FormRow label="名称" htmlFor="model-name" error={error || undefined} control={<Input id="model-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：DeepSeek 生产" />} />
          <div className="space-y-1.5">
            <Label className="text-xs text-muted">Provider</Label>
            <Select
              value={presetType}
              onValueChange={(v) => {
                setPresetType(v)
                const p = presets.find((x) => x.type === v)
                if (p) {
                  if (p.base_url) setBaseUrl(p.base_url)
                  if (p.model) setModelName(p.model)
                }
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择预设" />
              </SelectTrigger>
              <SelectContent>
                {presets.map((p) => (
                  <SelectItem key={p.type} value={p.type}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted">API 地址</Label>
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted">模型名</Label>
            <Input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="deepseek-chat" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted">API Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={model ? '留空表示保持不变' : '请输入 API Key'}
              autoComplete="new-password"
            />
            <p className="text-xs text-muted">密钥加密保存，接口不回显。</p>
          </div>
          <div className="flex items-center gap-2.5">
            <Switch id="mf-active" checked={active} onCheckedChange={setActive} />
            <Label htmlFor="mf-active" className="text-[13.5px]">
              激活
            </Label>
          </div>
        </div>
        <SheetFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" disabled={saving} onClick={() => void submit()}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
