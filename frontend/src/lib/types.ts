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
}

export interface SubmissionView {
  submission_id: number
  status: string
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
  summary: Record<string, number>
  created_at: string
  resolved_at: string | null
}

export interface IngestResult {
  source_id: number
  task_id: number
  secrets: { name: string; saved: boolean }[]
  secrets_count: number
  duplicate?: boolean
  message?: string
  pending_confirmation?: boolean
}

export interface QueryResult {
  answer: string
  citations: string[]
}

export interface ChatEntry {
  id: number
  question: string
  answer: string
  citations: string[]
  session_id: string | null
  title: string | null
  pinned: boolean
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
  status: string
  error: string | null
  retries: number
  original_name: string | null
  created_at: string
  updated_at: string
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

export interface DetectionRule {
  name: string
  kind: string
  enabled: boolean
  validator?: string | null
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
