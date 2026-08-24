import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, errMsg } from '@/lib/api'
import type { RetrievalConfigBody, RetrievalConfigView } from '@/lib/types'

const PROVIDER_LABELS: Record<string, string> = {
  'sentence-transformers': '本地 sentence-transformers',
  ollama: '本地 Ollama',
  cloud: '云端（OpenAI 兼容）',
}

const CUSTOM = '__custom__'

/** 设置页「检索配置」区：页面可读写，写入优先于环境变量；Key 加密存储、接口不回显。 */
export function RetrievalSection() {
  const [view, setView] = useState<RetrievalConfigView | null>(null)
  const [provider, setProvider] = useState('sentence-transformers')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [modelIsCustom, setModelIsCustom] = useState(false)
  const [rerankerEnabled, setRerankerEnabled] = useState(true)
  const [rerankerModel, setRerankerModel] = useState('')
  const [rerankerIsCustom, setRerankerIsCustom] = useState(false)
  const [customReranker, setCustomReranker] = useState('')
  const [cloudBaseUrl, setCloudBaseUrl] = useState('')
  const [cloudKey, setCloudKey] = useState('')
  const [cloudAck, setCloudAck] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string>('')

  const load = async () => {
    try {
      const v = await api.retrievalConfig()
      setView(v)
      setProvider(v.provider)
      applyModel(v.model, v.recommended.embeddings[v.provider] ?? [])
      setRerankerEnabled(v.reranker_enabled)
      applyReranker(v.reranker_model, v.recommended.rerankers)
      setCloudBaseUrl(v.cloud_base_url)
      setCloudKey('')
      setCloudAck(false)
      setTestResult('')
    } catch {
      setView(null)
    }
  }

  const applyModel = (m: string, recommended: string[]) => {
    if (recommended.includes(m)) {
      setModel(m)
      setModelIsCustom(false)
    } else {
      setModelIsCustom(true)
      setCustomModel(m)
    }
  }

  const applyReranker = (m: string, rerankers: string[]) => {
    if (rerankers.includes(m)) {
      setRerankerModel(m)
      setRerankerIsCustom(false)
    } else {
      setRerankerIsCustom(true)
      setCustomReranker(m)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const currentModel = () => (modelIsCustom ? customModel.trim() : model)
  const currentReranker = () => (rerankerIsCustom ? customReranker.trim() : rerankerModel)

  const body = (): RetrievalConfigBody => ({
    provider: provider as RetrievalConfigBody['provider'],
    model: currentModel(),
    reranker_enabled: rerankerEnabled,
    reranker_model: currentReranker(),
    cloud_base_url: cloudBaseUrl.trim(),
    cloud_api_key: cloudKey.trim(),
    cloud_ack: cloudAck,
  })

  const submit = async () => {
    const b = body()
    if (!b.model) return setTestResult('请填写模型名')
    if (provider === 'cloud') {
      if (!b.cloud_base_url) return setTestResult('云端路线请填写 API 地址')
      if (!b.cloud_ack) return setTestResult('请勾选确认：知识库内容将发送到该云端端点')
    }
    setSaving(true)
    setTestResult('')
    try {
      const r = await api.saveRetrievalConfig(b)
      toast.success(r.index_invalidated ? '已保存；索引已自动重建，正在更新检索。' : '检索配置已保存')
      await load()
    } catch (e) {
      setTestResult(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    const b = body()
    if (!b.model) return setTestResult('请填写模型名')
    setTesting(true)
    setTestResult('')
    try {
      const r = await api.testRetrieval(b)
      if (r.ok) setTestResult(`测试通过：模型可用，向量维度 ${r.dimension}`)
      else setTestResult(`测试失败：${r.error || '未知错误'}`)
    } catch (e) {
      setTestResult(`测试失败：${errMsg(e)}`)
    } finally {
      setTesting(false)
    }
  }

  const reset = async () => {
    try {
      await api.resetRetrieval()
      toast.success('已恢复环境变量默认配置')
      await load()
    } catch (e) {
      toast.error('恢复失败：' + errMsg(e))
    }
  }

  const embeddings = view?.recommended.embeddings[provider] ?? []
  const rerankers = view?.recommended.rerankers ?? []
  const cloudKeySet = view?.cloud_api_key_set

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-[17px] py-4">
        <div>
          <h2 className="text-input font-semibold">检索配置</h2>
          <p className="mt-1 text-caption text-muted">问答检索的 embedding 与重排模型；页面配置优先于环境变量。</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={view?.source === 'page' ? 'accent' : 'muted'}>
            {view?.source === 'page' ? '页面配置生效' : '环境变量生效'}
          </Badge>
          {view?.configured && (
            <Button variant="compact" size="sm" onClick={() => void reset()}>
              恢复环境变量默认
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-3.5 px-[17px] py-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1.5">
            <span className="text-xs text-muted">后端路线</span>
            <Select value={provider} onValueChange={(v) => {
              setProvider(v)
              setTestResult('')
              if (v !== 'cloud') {
                setCloudAck(false)
                setCloudKey('')
              }
            }}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(PROVIDER_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <span className="text-xs text-muted">模型名{modelIsCustom ? '' : '（推荐）'}</span>
            {modelIsCustom ? (
              <Input
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={provider === 'ollama' ? 'Ollama 模型名，如 bge-m3' : provider === 'cloud' ? '任意兼容模型名' : 'HuggingFace 模型 ID'}
              />
            ) : (
              <Select value={model} onValueChange={(v) => {
                if (v === CUSTOM) {
                  setModelIsCustom(true)
                  setCustomModel('')
                } else {
                  setModel(v)
                }
              }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {embeddings.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                  <SelectItem value={CUSTOM}>自定义模型…</SelectItem>
                </SelectContent>
              </Select>
            )}
            {modelIsCustom && (
              <Button variant="compact" size="sm" onClick={() => {
                setModelIsCustom(false)
                setModel(embeddings[0] ?? '')
              }}>
                使用推荐模型
              </Button>
            )}
          </div>
        </div>

        {provider === 'cloud' && (
          <div className="space-y-2 rounded-md border border-border bg-bg p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1.5">
                <span className="text-xs text-muted">API 地址</span>
                <Input value={cloudBaseUrl} onChange={(e) => setCloudBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
              </div>
              <div className="space-y-1.5">
                <span className="text-xs text-muted">API Key</span>
                <Input
                  type="password"
                  value={cloudKey}
                  onChange={(e) => setCloudKey(e.target.value)}
                  placeholder={cloudKeySet ? '已保存（留空保持不变）' : '请输入 API Key'}
                  autoComplete="new-password"
                />
              </div>
            </div>
            <div className="rounded-md border border-warn bg-warn-soft px-3 py-2 text-caption">
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={cloudAck} onChange={(e) => setCloudAck(e.target.checked)} className="mt-0.5" />
                <span>警告：选择云端端点后，知识库内容将发送到该端点。请确认该端点可信。</span>
              </label>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2.5">
          <Switch checked={rerankerEnabled} onCheckedChange={(v) => {
            setRerankerEnabled(v)
            setTestResult('')
          }} />
          <span className="text-[13.5px]">启用重排器（本地 cross-encoder 精排）</span>
        </div>
        {rerankerEnabled && (
          <div className="space-y-1.5">
            <span className="text-xs text-muted">重排模型{rerankerIsCustom ? '' : '（推荐）'}</span>
            {rerankerIsCustom ? (
              <Input value={customReranker} onChange={(e) => setCustomReranker(e.target.value)} placeholder="HuggingFace 重排模型 ID" />
            ) : (
              <Select value={rerankerModel} onValueChange={(v) => {
                if (v === CUSTOM) {
                  setRerankerIsCustom(true)
                  setCustomReranker('')
                } else {
                  setRerankerModel(v)
                }
              }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {rerankers.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                  <SelectItem value={CUSTOM}>自定义模型…</SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>
        )}

        <div className="flex items-center gap-2.5">
          <Button variant="compact" size="sm" disabled={testing} onClick={() => void test()}>
            {testing ? '测试中…' : '测试'}
          </Button>
          <Button variant="primary" size="sm" disabled={saving} onClick={() => void submit()}>
            {saving ? '保存中…' : '保存'}
          </Button>
          {testResult && <p className="text-caption">{testResult}</p>}
        </div>
        <p className="text-meta text-muted">保存后立即生效：embedding 与重排模型变更会触发索引自动重建。</p>
      </div>
    </section>
  )
}
