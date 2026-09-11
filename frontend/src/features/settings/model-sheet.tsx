import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Field, FieldContent, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
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
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          <FieldGroup className="gap-5">
            <Field>
              <FieldLabel>角色</FieldLabel>
              <Select value={role} disabled>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="knowledge">知识库（必配）</SelectItem>
                  <SelectItem value="security">安全增强（可选）</SelectItem>
                </SelectContent>
              </Select>
              <FieldDescription>{ROLE_HINTS[role] || ''}</FieldDescription>
            </Field>
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="model-name">名称</FieldLabel>
              <Input
                id="model-name"
                value={name}
                aria-invalid={!!error}
                onChange={(e) => { setName(e.target.value); if (error) setError('') }}
                placeholder="如：DeepSeek 生产"
              />
              <FieldError>{error}</FieldError>
            </Field>
            <Field>
              <FieldLabel>Provider</FieldLabel>
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
            </Field>
            <Field>
              <FieldLabel htmlFor="model-base-url">API 地址</FieldLabel>
              <Input id="model-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" />
            </Field>
            <Field>
              <FieldLabel htmlFor="model-model-name">模型名</FieldLabel>
              <Input id="model-model-name" value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="deepseek-chat" />
            </Field>
            <Field>
              <FieldLabel htmlFor="model-api-key">API Key</FieldLabel>
              <Input
                id="model-api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={model ? '留空表示保持不变' : '请输入 API Key'}
                autoComplete="new-password"
              />
              <FieldDescription>密钥加密保存，接口不回显。</FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="model-active">激活</FieldLabel>
                <FieldDescription>保存后立即生效。</FieldDescription>
              </FieldContent>
              <Switch id="model-active" checked={active} onCheckedChange={setActive} className="data-[state=checked]:bg-emerald-600" />
            </Field>
          </FieldGroup>
        </div>
        <SheetFooter className="flex-row justify-end">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            className="bg-emerald-600 text-white hover:bg-emerald-700"
            disabled={saving}
            onClick={() => void submit()}
          >
            {saving ? '保存中…' : '保存'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
