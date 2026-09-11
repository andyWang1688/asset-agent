import type {
  ChatEntry,
  CustomRuleBody,
  DetectionRule,
  FindingEdits,
  Health,
  IngestResult,
  ModelDownloadBody,
  ModelDownloadStart,
  ModelDownloadStatus,
  ModelBody,
  ModelRow,
  PendingSubmission,
  PolicyResp,
  PrivateRefMeta,
  Preset,
  QueryResult,
  RebuildStatus,
  ReportSnapshot,
  RetrievalConfigBody,
  RetrievalConfigView,
  RetrievalTestResult,
  SecurityEvent,
  SecuritySettingsView,
  SessionInfo,
  SessionMode,
  SettingsStatus,
  SubmissionView,
  TaskRow,
  TestResult,
  WikiDoc,
  WikiPage,
} from './types'

/** 统一 API 错误：解析后端 detail / message 与 HTTP 状态 */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : '请求失败'
}

async function request<T>(url: string, opts: RequestInit = {}): Promise<T> {
  const init: RequestInit = { ...opts }
  if (typeof init.body === 'string' && !init.headers) {
    init.headers = { 'Content-Type': 'application/json' }
  }
  const r = await fetch(url, init)
  const text = await r.text()
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    data = { detail: text }
  }
  if (!r.ok) {
    const d = data as { detail?: string; message?: string }
    throw new ApiError(r.status, d.detail || d.message || r.statusText || `请求失败（${r.status}）`)
  }
  return data as T
}

export interface StreamAction {
  action: string
  path?: string
  query?: string
}

export interface StreamHandlers {
  onReasoning?: (text: string) => void
  onAction?: (action: StreamAction) => void
  onRetry?: () => void
  onAnswer?: (result: QueryResult) => void
  onError?: (message: string) => void
}

function handleSseEvent(chunk: string, handlers: StreamHandlers): void {
  let event = 'message'
  let data = ''
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(data) as Record<string, unknown>
  } catch {
    return
  }
  if (event === 'reasoning') handlers.onReasoning?.(String(payload.text ?? ''))
  else if (event === 'action') handlers.onAction?.(payload as unknown as StreamAction)
  else if (event === 'retry') handlers.onRetry?.()
  else if (event === 'answer') handlers.onAnswer?.(payload as unknown as QueryResult)
  else if (event === 'error') handlers.onError?.(String(payload.message ?? '问答失败'))
}

/** 全部后端调用集中于此；不在组件内散落原始 fetch；不记录密钥与原文 */
export const api = {
  health: () => request<Health>('/api/health'),
  settingsStatus: () => request<SettingsStatus>('/api/settings/status'),

  ingest: (fd: FormData) => request<IngestResult>('/api/ingest', { method: 'POST', body: fd }),

  pendingSubmissions: () => request<PendingSubmission[]>('/api/pending/submissions'),
  submissionView: (id: number) => request<SubmissionView>(`/api/pending/submissions/${id}`),
  confirmSubmission: (
    id: number,
    decisions: Record<string, string>,
    sessionId: string,
    edits: FindingEdits,
    editedText?: string,
  ) =>
    request<IngestResult>(`/api/pending/submissions/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ decisions, edits, edited_text: editedText, session_id: sessionId }),
    }),
  cancelSubmission: (id: number) =>
    request<{ cancelled: boolean }>(`/api/pending/submissions/${id}/cancel`, { method: 'POST' }),

  query: (question: string, sessionId?: string | null) =>
    request<QueryResult>('/api/query', { method: 'POST', body: JSON.stringify({ question, session_id: sessionId ?? null }) }),
  /** SSE 问答流：推理增量 / 工具动作 / 重试实时回调，最后回调完整答案 */
  streamQuery: async (question: string, sessionId: string | null, handlers: StreamHandlers): Promise<void> => {
    const r = await fetch('/api/query/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, session_id: sessionId ?? null }),
    })
    if (!r.ok) {
      let detail = `请求失败（${r.status}）`
      try {
        const d = (await r.json()) as { detail?: string; message?: string }
        detail = d.detail || d.message || detail
      } catch {
        /* 非 JSON 错误体：保留状态码文案 */
      }
      throw new ApiError(r.status, detail)
    }
    if (!r.body) throw new Error('当前浏览器不支持流式响应')
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        handleSseEvent(buffer.slice(0, sep), handlers)
        buffer = buffer.slice(sep + 2)
        sep = buffer.indexOf('\n\n')
      }
    }
  },
  chatHistory: () => request<ChatEntry[]>('/api/chat/history'),
  createSession: (mode: SessionMode, sessionId?: string, title?: string) =>
    request<SessionInfo>('/api/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ mode, session_id: sessionId ?? null, title: title ?? null }),
    }),
  listSessions: () => request<SessionInfo[]>('/api/chat/sessions'),
  setSessionTitle: (sessionId: string, title: string) =>
    request<{ ok: boolean }>('/api/chat/session/title', { method: 'POST', body: JSON.stringify({ session_id: sessionId, title }) }),
  setSessionPin: (sessionId: string, pinned: boolean) =>
    request<{ ok: boolean }>('/api/chat/session/pin', { method: 'POST', body: JSON.stringify({ session_id: sessionId, pinned }) }),
  adoptSession: (sessionId: string, entryIds: number[]) =>
    request<{ ok: boolean }>('/api/chat/session/adopt', { method: 'POST', body: JSON.stringify({ session_id: sessionId, entry_ids: entryIds }) }),
  deleteSession: (sessionId: string) =>
    request<{ ok: boolean }>('/api/chat/session?session_id=' + encodeURIComponent(sessionId), { method: 'DELETE' }),

  wikiPages: () => request<WikiPage[]>('/api/wiki/pages'),
  wikiPage: (path: string) => request<WikiDoc>(`/api/wiki/page?path=${encodeURIComponent(path)}`),
  wikiRebuild: () => request<{ ok: boolean }>('/api/wiki/rebuild', { method: 'POST' }),

  tasks: () => request<TaskRow[]>('/api/tasks'),
  reports: (sessionId?: string) =>
    request<ReportSnapshot[]>(`/api/reports${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`),
  reportView: (id: number) => request<ReportSnapshot>(`/api/reports/${id}`),
  refMetadata: (refId: string) => request<PrivateRefMeta>(`/api/refs/${encodeURIComponent(refId)}`),

  presets: () => request<Preset[]>('/api/settings/presets'),
  models: () => request<ModelRow[]>('/api/settings/models'),
  saveModel: (body: ModelBody) => request<{ id: number }>('/api/settings/models', { method: 'POST', body: JSON.stringify(body) }),
  activateModel: (id: number) => request<{ ok: boolean }>(`/api/settings/models/${id}/activate`, { method: 'POST' }),
  testModel: (id: number) => request<TestResult>(`/api/settings/models/${id}/test`, { method: 'POST' }),
  deleteModel: (id: number) => request<{ ok: boolean }>(`/api/settings/models/${id}`, { method: 'DELETE' }),

  retrievalConfig: () => request<RetrievalConfigView>('/api/settings/retrieval'),
  saveRetrievalConfig: (body: RetrievalConfigBody) =>
    request<{ ok: boolean; rebuild_triggered: boolean; config: RetrievalConfigView }>('/api/settings/retrieval', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  retrievalRebuildStatus: () => request<RebuildStatus>('/api/settings/retrieval/rebuild/status'),
  testRetrieval: (body: RetrievalConfigBody) =>
    request<RetrievalTestResult>('/api/settings/retrieval/test', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  startModelDownload: (body: ModelDownloadBody) =>
    request<ModelDownloadStart>('/api/settings/retrieval/download', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  modelDownloadStatus: (model: string) =>
    request<ModelDownloadStatus>(`/api/settings/retrieval/download/status?model=${encodeURIComponent(model)}`),
  resetRetrieval: () => request<{ ok: boolean }>('/api/settings/retrieval', { method: 'DELETE' }),

  securitySettings: () => request<SecuritySettingsView>('/api/settings/security'),
  updateSecuritySettings: (body: Partial<SecuritySettingsView>) =>
    request<SecuritySettingsView & { ok?: boolean }>('/api/settings/security', { method: 'PATCH', body: JSON.stringify(body) }),
  policy: () => request<PolicyResp>('/api/settings/policy'),
  savePolicy: (yaml: string) => request<{ ok: boolean; policy: unknown }>('/api/settings/policy', { method: 'POST', body: JSON.stringify({ yaml }) }),
  policyRules: () => request<{ rules: DetectionRule[]; validators: string[] }>('/api/settings/policy/rules'),
  builtinRules: () => request<{ rules: DetectionRule[] }>('/api/settings/policy/builtin-rules'),
  setBuiltinRule: (name: string, enabled: boolean) =>
    request<{ ok: boolean; rule: DetectionRule }>(`/api/settings/policy/builtin-rules/${encodeURIComponent(name)}`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
  setBuiltinOverride: (name: string, body: { pattern?: string; kind?: string }) =>
    request<{ ok: boolean; rule: DetectionRule }>(`/api/settings/policy/builtin-rules/${encodeURIComponent(name)}/override`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  restoreBuiltinOverride: (name: string) =>
    request<{ ok: boolean; rule: DetectionRule }>(`/api/settings/policy/builtin-rules/${encodeURIComponent(name)}/override`, { method: 'DELETE' }),
  customRules: () => request<{ rules: DetectionRule[]; validators: string[] }>('/api/settings/policy/custom-rules'),
  addCustomRule: (body: CustomRuleBody) =>
    request<{ ok: boolean; rule: DetectionRule }>('/api/settings/policy/custom-rules', { method: 'POST', body: JSON.stringify(body) }),
  setCustomRule: (name: string, enabled: boolean) =>
    request<{ ok: boolean; rule: DetectionRule }>(`/api/settings/policy/custom-rules/${encodeURIComponent(name)}`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
  deleteCustomRule: (name: string) =>
    request<{ ok: boolean }>(`/api/settings/policy/custom-rules/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  securityEvents: () => request<SecurityEvent[]>('/api/security/events'),
  clearSecurityEvents: () => request<{ ok: boolean }>('/api/security/events', { method: 'DELETE' }),
}

export default api
