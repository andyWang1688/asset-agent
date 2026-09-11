import type { components } from './apiTypes'

/**
 * 请求体类型直接取自 openapi-typescript 生成的 apiTypes.ts（pnpm gen:api 可重复生成）。
 * 响应类型：后端接口未声明 response_model，返回结构为无模式 dict，
 * 这里按现有 API 的实际响应形状声明（与 app/api.py 保持一致）。
 */

export type ModelBody = components['schemas']['ModelBody']
export type ConfirmBody = components['schemas']['ConfirmBody']
export type QueryBody = components['schemas']['QueryBody']
export type PolicyBody = components['schemas']['PolicyBody']

export type SessionMode = 'ask' | 'maintain'

export interface SessionInfo {
  session_id: string
  mode: SessionMode
  title: string | null
  pinned: boolean
  created_at: string
}

/** 后端未声明 response_model，health 响应无 OpenAPI 模式，按实际形状显式声明 */
export interface Health {
  status: string
  vaultwarden_cli: boolean
  vaultwarden_configured: boolean
  model: boolean
  knowledge_model: boolean
  security_model: boolean
  pending_secrets: number
}

export interface SettingsStatus {
  knowledge_model: boolean
  retrieval_degraded: boolean
  retrieval_checked: boolean
  rules_enabled: number
  rules_total: number
  policy_valid: boolean
  pending_security_events: number
}

export interface Finding {
  id: string
  kind: string
  rule: string
  confidence: number
  evidence: string
  suggested_action: string
  allowed_actions: string[]
  detector: string
  context: string
  name: string
  description: string
  source: string
  ref_id: string
  private_ref: string | null
  vault: { kind: string; name: string; field_name: string }
}

export interface SubmissionView {
  submission_id: number
  status: string
  session_id: string | null
  report_id: number | null
  original_name: string
  created_at: string
  summary: Record<string, number>
  findings: Finding[]
  preview: string
}

export interface PendingSubmission {
  id: number
  status: string
  sha256: string
  original_name: string | null
  session_id: string | null
  report_id: number | null
  summary: Record<string, number>
  created_at: string
  resolved_at: string | null
}

/** 确认请求中每个 Finding 的可编辑字段（后端 FindingEditBody） */
export type FindingEdits = Record<string, {
  type?: string
  name?: string
  description?: string
  vault_kind?: string
  vault_name?: string
  field_name?: string
}>

export interface IngestResult {
  source_id: number
  task_id: number
  report_id?: number
  secrets: { name: string; saved: boolean }[]
  secrets_count: number
  duplicate?: boolean
  message?: string
  pending_confirmation?: boolean
}

export interface QueryResult {
  answer: string
  citations: string[]
  semantic_retrieval_enabled?: boolean
}

export interface ChatEntry {
  id: number
  question: string
  answer: string
  citations: string[]
  session_id: string | null
  title: string | null
  pinned: boolean
  mode: SessionMode
  created_at: string
}

export interface WikiPage {
  path: string
  title: string
}

export interface WikiDoc {
  path: string
  content: string
}

export interface TaskRow {
  id: number
  source_id: number
  session_id: string | null
  report_id: number | null
  status: string
  error: string | null
  result?: { changes?: string[]; conflicts?: { between?: string[]; note?: string }[] }
  retries: number
  original_name: string | null
  created_at: string
  updated_at: string
}

export interface ReportEntry {
  finding_id: string
  type: string
  name: string
  description: string
  source: string
  action: string
  rule: string
  confidence: number
  detector: string
  value_hash?: string
  span?: [number, number]
  ref_id: string
  private_ref: string | null
  vault: {
    kind: string
    name: string
    field_name: string
    item_id: string | null
    saved: boolean
    pending_id?: number | null
  }
}

export interface ReportSnapshot {
  id: number
  session_id: string | null
  submission_id: number | null
  status: 'pending' | 'confirmed' | 'auto' | 'rejected'
  mode: 'confirm' | 'auto'
  kind: string
  original_name: string
  sha256: string
  summary: Record<string, number>
  entries: ReportEntry[]
  preview: string
  instruction: string
  created_at: string
  confirmed_at: string | null
}

export interface PrivateRefMeta {
  ref_id: string
  name: string | null
  source: string
  kind: string
  vault_kind: string | null
  vault_name: string | null
  field_name: string | null
  item_id: string | null
  report_id: number
  session_id: string | null
  created_at: string
}

export interface Preset {
  type: string
  name: string
  base_url: string
  model: string
}

export interface ModelRow {
  id: number
  name: string
  provider_type: string
  base_url: string
  api_key_set: boolean
  model: string
  is_active: boolean
  role: string
}

export interface SecurityEvent {
  id: number
  kind: string
  detail: string
  created_at: string
}

export interface PolicyResp {
  policy: unknown
  yaml: string
}

export type SecurityMode = 'default' | 'confirm'
export type EntropySensitivity = 'sensitive' | 'balanced' | 'conservative' | 'custom'

export interface SecuritySettingsView {
  mode: SecurityMode
  keywords: { enabled: boolean; items: string[] }
  entropy: { enabled: boolean; sensitivity: EntropySensitivity }
}

export interface DetectionRule {
  name: string
  kind: string
  enabled: boolean
  validator?: string | null
  description?: string
  examples?: string[]
  pattern?: string
  source?: 'builtin' | 'override' | 'custom'
}

export interface CustomRuleBody {
  name: string
  pattern: string
  kind: string
  validator?: string
}

export interface TestResult {
  ok: boolean
  reply?: string
  error?: string
}

export interface RetrievalConfigView {
  configured: boolean
  source: 'page' | 'env'
  provider: 'sentence-transformers' | 'ollama' | 'cloud'
  model: string
  reranker_enabled: boolean
  reranker_model: string
  cloud_base_url: string
  cloud_api_key_set: boolean
  recommended: {
    embeddings: Record<string, string[]>
    rerankers: string[]
  }
}

export interface RetrievalConfigBody {
  provider: 'sentence-transformers' | 'ollama' | 'cloud'
  model: string
  reranker_enabled: boolean
  reranker_model: string
  cloud_base_url: string
  cloud_api_key: string
  cloud_ack: boolean
}

export interface RetrievalTestResult {
  ok: boolean
  dimension?: number
  error?: string
}

export interface RebuildStatus {
  status: 'idle' | 'queued' | 'running' | 'done' | 'failed'
  pages: number
  embedding: string
  error: string
  started_at: number | null
  finished_at: number | null
}

export interface ModelDownloadBody {
  provider: string
  model: string
}

export interface ModelDownloadStatus {
  model: string
  status: 'unknown' | 'queued' | 'downloading' | 'done' | 'failed'
  downloaded: boolean
  progress: number
  files_done: number
  files_total: number
  bytes_done: number
  bytes_total: number
  error: string
  started_at: number | null
  finished_at: number | null
}

export interface ModelDownloadStart {
  ok: boolean
  started: boolean
  download: ModelDownloadStatus
}
