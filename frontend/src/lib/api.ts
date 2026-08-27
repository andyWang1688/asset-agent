import type {
  ChatEntry,
  CustomRuleBody,
  DetectionRule,
  Health,
  IngestResult,
  ModelDownloadBody,
  ModelDownloadStart,
  ModelDownloadStatus,
  ModelBody,
  ModelRow,
  PendingSubmission,
  PolicyResp,
  Preset,
  QueryResult,
  RebuildStatus,
  RetrievalConfigBody,
  RetrievalConfigView,
  RetrievalTestResult,
  SecurityEvent,
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

/** 全部后端调用集中于此；不在组件内散落原始 fetch；不记录密钥与原文 */
export const api = {
  health: () => request<Health>('/api/health'),
  settingsStatus: () => request<SettingsStatus>('/api/settings/status'),

  ingest: (fd: FormData) => request<IngestResult>('/api/ingest', { method: 'POST', body: fd }),

  pendingSubmissions: () => request<PendingSubmission[]>('/api/pending/submissions'),
  submissionView: (id: number) => request<SubmissionView>(`/api/pending/submissions/${id}`),
  confirmSubmission: (id: number, decisions: Record<string, string>, editedText?: string) =>
    request<IngestResult>(`/api/pending/submissions/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ decisions, edited_text: editedText }),
    }),
  cancelSubmission: (id: number) =>
    request<{ cancelled: boolean }>(`/api/pending/submissions/${id}/cancel`, { method: 'POST' }),

  query: (question: string, sessionId?: string | null) =>
    request<QueryResult>('/api/query', { method: 'POST', body: JSON.stringify({ question, session_id: sessionId ?? null }) }),
  chatHistory: () => request<ChatEntry[]>('/api/chat/history'),
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
  retryTask: (id: number) => request<{ id: number; status: string }>(`/api/tasks/${id}/retry`, { method: 'POST' }),

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

  securityEvents: () => request<SecurityEvent[]>('/api/security/events'),
}

export default api
