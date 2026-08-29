import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { CUSTOM, PROVIDER_LABELS, sizeHint, useRetrievalConfig } from './use-retrieval-config'
import { DownloadPanel } from './retrieval-fields'

/** 设置页「检索配置」区：状态与网络交互见 useRetrievalConfig，本组件只编排视图 */
export function RetrievalSection({ onStatusChange }: { onStatusChange?: () => void }) {
  const {
    view, provider, setProvider, model, setModel, customModel, setCustomModel, modelIsCustom, setModelIsCustom,
    rerankerEnabled, setRerankerEnabled, rerankerModel, setRerankerModel, rerankerIsCustom, setRerankerIsCustom,
    customReranker, setCustomReranker, cloudBaseUrl, setCloudBaseUrl, cloudKey, setCloudKey, cloudAck, setCloudAck,
    saving, testing, testResult, setTestResult, rebuild, dlStatus, downloading,
    currentModel, submit, test, reset, startDownload,
    embeddings, rerankers, cloudKeySet,
  } = useRetrievalConfig(onStatusChange)

  return (
    <section>
      <div className="flex items-center justify-end gap-2 border-b border-border px-cell py-3">
        <Badge variant={view?.source === 'page' ? 'accent' : 'muted'}>
          {view?.source === 'page' ? '页面配置生效' : '环境变量生效'}
        </Badge>
        {view?.configured && (
          <Button variant="compact" size="sm" onClick={() => void reset()}>
            恢复环境变量默认
          </Button>
        )}
      </div>

      <div className="space-y-3.5 px-cell py-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1.5">
            <span className="text-caption text-muted">后端路线</span>
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
            <span className="text-caption text-muted">模型名{modelIsCustom ? '' : '（推荐）'}</span>
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
                  {embeddings.map((m) => <SelectItem key={m} value={m}>{sizeHint(m)}</SelectItem>)}
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
            <DownloadPanel
              downloading={downloading}
              dlStatus={dlStatus}
              canDownload={!!currentModel()}
              onStart={() => void startDownload()}
            />
            {provider === 'ollama' && (
              <p className="pt-1 text-meta text-muted">Ollama 模型请在终端执行 `ollama pull 模型名` 拉取后再测试。</p>
            )}
          </div>
        </div>

        {provider === 'cloud' && (
          <div className="space-y-2 rounded-md border border-border bg-bg p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1.5">
                <span className="text-caption text-muted">API 地址</span>
                <Input value={cloudBaseUrl} onChange={(e) => setCloudBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
              </div>
              <div className="space-y-1.5">
                <span className="text-caption text-muted">API Key</span>
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
            <span className="text-caption text-muted">重排模型{rerankerIsCustom ? '' : '（推荐）'}</span>
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
                  {rerankers.map((m) => <SelectItem key={m} value={m}>{sizeHint(m)}</SelectItem>)}
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
        {rebuild && (rebuild.status === 'queued' || rebuild.status === 'running') && (
          <p className="text-meta text-muted">索引重建中（{rebuild.pages > 0 ? `${rebuild.pages} 页` : '进行中'}）…旧索引继续服务。</p>
        )}
        {rebuild && rebuild.status === 'failed' && (
          <p className="text-meta text-danger">索引重建失败：{rebuild.error || '未知错误'}。修正模型后可重新保存触发重建。</p>
        )}
        <p className="text-meta text-muted">保存后立即生效：embedding 变更会触发索引自动重建，重建期间旧索引继续服务。</p>
      </div>
    </section>
  )
}