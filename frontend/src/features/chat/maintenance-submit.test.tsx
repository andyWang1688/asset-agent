// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  createSession: vi.fn(async (mode: string) => ({ session_id: 'created', mode, title: null, pinned: false, created_at: '' })),
  ingest: vi.fn(),
  query: vi.fn(async () => ({ answer: 'ok', citations: [] })),
  chatHistory: vi.fn(async () => []),
  listSessions: vi.fn(async () => []),
  reports: vi.fn<(sid?: string) => Promise<unknown>>(async () => []),
  tasks: vi.fn<() => Promise<unknown>>(async () => []),
  pendingSubmissions: vi.fn(async () => []),
  submissionView: vi.fn(),
  confirmSubmission: vi.fn(),
  cancelSubmission: vi.fn(),
  health: vi.fn(async () => ({ status: 'ok', knowledge_model: true, security_model: false, model: true })),
}))
vi.mock('@/lib/api', () => ({ api: apiMock, errMsg: (e: unknown) => String(e) }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, describe, expect, it } from 'vitest'
import { AppProvider } from '@/store/app-context'
import { useChat } from '@/hooks/use-chat'
import { ChatPage } from './chat-page'

let root: Root | null = null
function Harness() {
  const chat = useChat()
  return createElement(ChatPage, { chat })
}
async function mount() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
  await act(async () => { root!.render(createElement(AppProvider, null, createElement(Harness))) })
  await act(async () => {})
}

beforeEach(() => {
  sessionStorage.clear()
  apiMock.ingest.mockReset()
})

describe('维护提交', () => {
  it('首次维护提交创建会话后展示确认闸门', async () => {
    let resolveIngest!: (v: unknown) => void
    apiMock.ingest.mockReturnValue(new Promise((r) => { resolveIngest = r }))
    await mount()
    const choose = [...document.querySelectorAll('[aria-label="对话模式"] button')].find((b) => b.textContent === '维护') as HTMLButtonElement
    await act(async () => { choose.click() })
    const area = document.querySelector('textarea')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, 'A safe document')
      area.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { [...document.querySelectorAll('button')].find((b) => b.textContent === '发送')!.click() })
    expect(apiMock.ingest).toHaveBeenCalledTimes(1)
    await act(async () => {
      resolveIngest({ pending_confirmation: true, submission_id: 9, session_id: 'created', report_id: 1, original_name: 'a.txt', status: 'waiting', preview: 'A safe document', findings: [], summary: {} })
    })
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('敏感信息确认')
  })

  it('首次自动维护提交后加载真实报告与任务', async () => {
    let resolveIngest!: (v: unknown) => void
    apiMock.ingest.mockReturnValue(new Promise((r) => { resolveIngest = r }))
    await mount()
    const choose = [...document.querySelectorAll('[aria-label="对话模式"] button')].find((b) => b.textContent === '维护') as HTMLButtonElement
    await act(async () => { choose.click() })
    const area = document.querySelector('textarea')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, 'Automatic safe document')
      area.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => { [...document.querySelectorAll('button')].find((b) => b.textContent === '发送')!.click() })
    apiMock.reports.mockResolvedValue([{ id: 1, session_id: 'created', status: 'auto', original_name: 'AUTO-ROUND.txt', preview: 'Automatic safe document', entries: [], created_at: '2026-09-08 12:00:00' }])
    apiMock.tasks.mockResolvedValue([{ id: 2, report_id: 1, session_id: 'created', status: 'done' }])
    await act(async () => { resolveIngest({ source_id: 1, task_id: 2, report_id: 1, secrets: [], secrets_count: 0 }) })
    expect(document.body.textContent).toContain('AUTO-ROUND.txt')
    expect(document.body.textContent).toContain('成功')
  })
})
