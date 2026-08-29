import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, errMsg } from '@/lib/api'
import type { ModelDownloadStatus, RebuildStatus, RetrievalConfigBody, RetrievalConfigView } from '@/lib/types'

export const PROVIDER_LABELS: Record<string, string> = {
  'sentence-transformers': '本地 sentence-transformers',
  ollama: '本地 Ollama',
  cloud: '云端（OpenAI 兼容）',
}

export const CUSTOM = '__custom__'

/** 推荐模型的规模标注（列表展示；未命中的模型只显示 ID） */
const SIZE_HINTS: Record<string, string> = {
  'bge-small-zh': '小 · 约 95MB · 入门',
  'bge-base-zh': '中 · 约 400MB · 均衡',
  'bge-large-zh': '大 · 约 1.3GB · 最佳效果',
  'bge-m3': '约 1.2GB · 多语言',
  'bge-reranker-base': '入门款',
  'bge-reranker-v2-m3': '多语言 · 更强',
}

export const sizeHint = (id: string): string => {
  const key = Object.keys(SIZE_HINTS).find((k) => id.toLowerCase().includes(k))
  return key ? `${id}（${SIZE_HINTS[key]}）` : id
}

/** 设置页「检索配置」区：页面可读写，写入优先于环境变量；Key 加密存储、接口不回显。 */

/** 检索配置的全部状态与网络交互；视图层只消费返回值 */
export function useRetrievalConfig(onStatusChange?: () => void) {
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
  const [rebuild, setRebuild] = useState<RebuildStatus | null>(null)
  const [dlStatus, setDlStatus] = useState<ModelDownloadStatus | null>(null)
  const [downloading, setDownloading] = useState(false)
  const dlTimer = useRef<number | null>(null)

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

  const stopDlPoll = () => {
    if (dlTimer.current !== null) {
      window.clearTimeout(dlTimer.current)
      dlTimer.current = null
    }
  }
  useEffect(() => stopDlPoll, [])

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
      if (r.rebuild_triggered) {
        toast.success('已保存；索引正在后台重建，重建期间旧索引继续服务。')
        void pollRebuild()
      } else {
        toast.success('检索配置已保存')
      }
      await load()
      onStatusChange?.()
    } catch (e) {
      setTestResult(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  /** 轮询索引重建状态直到完成/失败；期间显示进行中提示。 */
  const pollRebuild = async () => {
    const tick = async () => {
      try {
        const s = await api.retrievalRebuildStatus()
        setRebuild(s)
        if (s.status === 'done') {
          toast.success('索引重建完成')
          return
        }
        if (s.status === 'failed') {
          toast.error('索引重建失败：' + (s.error || '未知错误'))
          return
        }
      } catch {
        return
      }
      window.setTimeout(() => void tick(), 1500)
    }
    void tick()
  }

  /** 页面打开时若已有后台重建，继续展示进度直到完成 */
  useEffect(() => {
    void api.retrievalRebuildStatus().then((s) => {
      if (s.status === 'queued' || s.status === 'running') {
        setRebuild(s)
        void pollRebuild()
      }
    }).catch(() => {})
  }, [])

  /** 轮询单个模型下载进度；done/failed 时停止并提示 */
  const pollDownload = (model: string) => {
    const tick = async () => {
      try {
        const s = await api.modelDownloadStatus(model)
        setDlStatus(s)
        if (s.status === 'done' || s.status === 'failed') {
          setDownloading(false)
          if (s.status === 'done') toast.success('模型已下载到本地')
          else toast.error(s.error || '模型下载失败')
          return
        }
      } catch {
        setDownloading(false)
        return
      }
      dlTimer.current = window.setTimeout(() => void tick(), 1000)
    }
    void tick()
  }

  const startDownload = async () => {
    const model = currentModel()
    if (!model || downloading) return
    setDownloading(true)
    setTestResult('')
    try {
      const r = await api.startModelDownload({ provider, model })
      setDlStatus(r.download)
      if (r.download.status === 'done') {
        toast.success('模型已在本地，无需重复下载')
        setDownloading(false)
        return
      }
      pollDownload(model)
    } catch (e) {
      setDownloading(false)
      setTestResult(errMsg(e))
    }
  }

  /** 模型/路线变化时刷新下载状态（本地 sentence-transformers 才有权重下载） */
  useEffect(() => {
    stopDlPoll()
    setDownloading(false)
    const model = currentModel()
    setDlStatus(null)
    if (provider !== 'sentence-transformers' || !model) return
    void api.modelDownloadStatus(model).then(setDlStatus).catch(() => setDlStatus(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, model, customModel])

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
      onStatusChange?.()
    } catch (e) {
      toast.error('恢复失败：' + errMsg(e))
    }
  }

  const embeddings = view?.recommended.embeddings[provider] ?? []
  const rerankers = view?.recommended.rerankers ?? []
  const cloudKeySet = view?.cloud_api_key_set
  return {
    view, provider, setProvider, model, setModel, customModel, setCustomModel, modelIsCustom, setModelIsCustom,
    rerankerEnabled, setRerankerEnabled, rerankerModel, setRerankerModel, rerankerIsCustom, setRerankerIsCustom,
    customReranker, setCustomReranker, cloudBaseUrl, setCloudBaseUrl, cloudKey, setCloudKey, cloudAck, setCloudAck,
    saving, testing, testResult, setTestResult, rebuild, dlStatus, downloading,
    currentModel, submit, test, reset, startDownload,
    embeddings, rerankers, cloudKeySet,
  }
}
