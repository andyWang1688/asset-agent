import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { CUSTOM, PROVIDER_LABELS, sizeHint, useRetrievalConfig } from './use-retrieval-config'
import { DownloadPanel } from './retrieval-fields'
import { SettingsGroup, SettingsRow } from './settings-ui'

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

  const rebuilding = rebuild && (rebuild.status === 'queued' || rebuild.status === 'running')

  return (
    <SettingsGroup
      title="向量检索"
      badge={<Badge variant="outline">{view?.source === 'page' ? '页面配置生效' : '环境变量生效'}</Badge>}
      description="用于历史资料的语义检索；保存后触发索引重建，重建期间旧索引继续服务。"
      action={
        <div className="flex items-center gap-2">
          {view?.configured && (
            <Button size="sm" variant="ghost" onClick={() => void reset()}>
              恢复默认
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={testing} onClick={() => void test()}>
            {testing ? '测试中…' : '测试'}
          </Button>
          <Button
            size="sm"
            className="bg-emerald-600 text-white hover:bg-emerald-700"
            disabled={saving}
            onClick={() => void submit()}
          >
            {saving ? '保存中…' : '保存'}
          </Button>
        </div>
      }
    >
      <SettingsRow
        label="后端路线"
        control={
          <Select
            value={provider}
            onValueChange={(v) => {
              setProvider(v)
              setTestResult('')
              if (v !== 'cloud') {
                setCloudAck(false)
                setCloudKey('')
              }
            }}
          >
            <SelectTrigger className="w-64" aria-label="后端路线">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(PROVIDER_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      <SettingsRow
        label="模型名"
        description={modelIsCustom ? '自定义模型 ID，将按原样使用。' : '推荐模型按规模与效果标注。'}
        control={
          modelIsCustom ? (
            <>
              <Input
                className="w-full sm:w-72"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={provider === 'ollama' ? 'Ollama 模型名，如 bge-m3' : provider === 'cloud' ? '任意兼容模型名' : 'HuggingFace 模型 ID'}
                aria-label="自定义模型名"
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setModelIsCustom(false)
                  setModel(embeddings[0] ?? '')
                }}
              >
                使用推荐
              </Button>
            </>
          ) : (
            <Select
              value={model}
              onValueChange={(v) => {
                if (v === CUSTOM) {
                  setModelIsCustom(true)
                  setCustomModel('')
                } else {
                  setModel(v)
                }
              }}
            >
              <SelectTrigger className="w-64" aria-label="模型名">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {embeddings.map((m) => <SelectItem key={m} value={m}>{sizeHint(m)}</SelectItem>)}
                <SelectItem value={CUSTOM}>自定义模型…</SelectItem>
              </SelectContent>
            </Select>
          )
        }
      />
      <SettingsRow
        label="模型下载"
        description={provider === 'ollama' ? 'Ollama 模型请在终端执行 ollama pull 模型名 拉取后再测试。' : '本地 sentence-transformers 路线需要先下载模型权重。'}
        control={
          <DownloadPanel
            downloading={downloading}
            dlStatus={dlStatus}
            canDownload={!!currentModel()}
            onStart={() => void startDownload()}
          />
        }
      />
      {provider === 'cloud' && (
        <>
          <SettingsRow
            label="API 地址"
            control={
              <Input
                className="w-full sm:w-80"
                value={cloudBaseUrl}
                onChange={(e) => setCloudBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
                aria-label="云端 API 地址"
              />
            }
          />
          <SettingsRow
            label="API Key"
            description={cloudKeySet ? '已保存（留空保持不变）。' : '密钥加密保存，接口不回显。'}
            control={
              <Input
                className="w-full sm:w-80"
                type="password"
                value={cloudKey}
                onChange={(e) => setCloudKey(e.target.value)}
                placeholder={cloudKeySet ? '已保存（留空保持不变）' : '请输入 API Key'}
                autoComplete="new-password"
                aria-label="云端 API Key"
              />
            }
          />
          <SettingsRow
            label="内容将发送到云端"
            description="选择云端端点后，知识库内容将发送到该端点。请确认该端点可信。"
            control={
              <input
                type="checkbox"
                checked={cloudAck}
                onChange={(e) => setCloudAck(e.target.checked)}
                className="size-4 accent-emerald-600"
                aria-label="确认云端端点可信"
              />
            }
          />
        </>
      )}
      <SettingsRow
        label="启用重排器"
        description="本地 cross-encoder 精排，提升召回质量。"
        control={
          <Switch
            checked={rerankerEnabled}
            onCheckedChange={(v) => {
              setRerankerEnabled(v)
              setTestResult('')
            }}
            className="data-[state=checked]:bg-emerald-600"
            aria-label="启用重排器"
          />
        }
      />
      {rerankerEnabled && (
        <SettingsRow
          label="重排模型"
          control={
            rerankerIsCustom ? (
              <Input
                className="w-full sm:w-72"
                value={customReranker}
                onChange={(e) => setCustomReranker(e.target.value)}
                placeholder="HuggingFace 重排模型 ID"
                aria-label="自定义重排模型"
              />
            ) : (
              <Select
                value={rerankerModel}
                onValueChange={(v) => {
                  if (v === CUSTOM) {
                    setRerankerIsCustom(true)
                    setCustomReranker('')
                  } else {
                    setRerankerModel(v)
                  }
                }}
              >
                <SelectTrigger className="w-64" aria-label="重排模型">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {rerankers.map((m) => <SelectItem key={m} value={m}>{sizeHint(m)}</SelectItem>)}
                  <SelectItem value={CUSTOM}>自定义模型…</SelectItem>
                </SelectContent>
              </Select>
            )
          }
        />
      )}
      {testResult && (
        <p
          className={`border-b px-4 py-3 text-xs last:border-b-0 ${testResult.startsWith('测试通过') ? 'text-emerald-600' : 'text-destructive'}`}
        >
          {testResult}
        </p>
      )}
      {rebuilding && (
        <p className="border-b px-4 py-3 text-xs text-muted-foreground last:border-b-0">
          索引重建中（{rebuild.pages > 0 ? `${rebuild.pages} 页` : '进行中'}）…旧索引继续服务。
        </p>
      )}
      {rebuild?.status === 'failed' && (
        <p className="border-b px-4 py-3 text-xs text-destructive last:border-b-0">
          索引重建失败：{rebuild.error || '未知错误'}。修正模型后可重新保存触发重建。
        </p>
      )}
      <p className="border-b px-4 py-3 text-xs text-muted-foreground last:border-b-0">
        保存后立即生效：embedding 变更会触发索引自动重建，重建期间旧索引继续服务。
      </p>
    </SettingsGroup>
  )
}
