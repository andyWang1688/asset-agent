// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  createSession: vi.fn(),
  query: vi.fn(),
  chatHistory: vi.fn(),
  listSessions: vi.fn(),
}))
vi.mock('@/lib/api', () => ({
  api: apiMock,
  errMsg: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useChat } from './use-chat'

let root: Root | null = null
let latest: ReturnType<typeof useChat> | null = null

function Harness() {
  const chat = useChat()
  latest = chat
  return createElement('div')
}

async function render() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root!.render(createElement(Harness)) })
}

beforeEach(() => {
  apiMock.createSession.mockReset()
  apiMock.query.mockReset()
  apiMock.chatHistory.mockReset()
  apiMock.listSessions.mockReset()
  apiMock.listSessions.mockResolvedValue([])
  sessionStorage.clear()
  apiMock.createSession.mockImplementation(async (mode: string) => ({ session_id: 's-1', mode, title: null, pinned: false, created_at: '' }))
  apiMock.query.mockResolvedValue({ answer: 'ok', citations: [] })
  apiMock.chatHistory.mockResolvedValue([])
})

afterEach(() => {
  if (root) act(() => root!.unmount())
  root = null
  latest = null
  document.body.innerHTML = ''
})

describe('会话模式锁定', () => {
  it('首次发送用所选模式创建后端 Session 并锁定', async () => {
    await render()
    expect(latest!.mode).toBeNull()
    await act(async () => { await latest!.ensureSession('maintain') })
    expect(latest!.mode).toBe('maintain')
    expect(apiMock.createSession).toHaveBeenCalledWith('maintain')
    expect(latest!.sessionId).toBe('s-1')
  })

  it('已锁定后不能再切换到另一模式', async () => {
    await render()
    await act(async () => { await latest!.ensureSession('maintain') })
    await expect(act(async () => { await latest!.ensureSession('ask') })).rejects.toThrow('不能切换')
  })

  it('newChat 回到草稿阶段', async () => {
    await render()
    await act(async () => { await latest!.ensureSession('ask') })
    await act(async () => { latest!.newChat() })
    expect(latest!.mode).toBeNull()
    expect(latest!.sessionId).toBeNull()
  })

  it('过期的 createSession 结果不覆盖已打开的新会话', async () => {
    let resolveCreate!: (v: unknown) => void
    apiMock.createSession.mockImplementation(() => new Promise((r) => { resolveCreate = r }))
    await render()
    let old: Promise<unknown>
    await act(async () => { old = latest!.ensureSession('ask').catch(() => {}) })
    await act(async () => { latest!.openSession('new-maintenance', 'maintain', []) })
    await act(async () => { resolveCreate({ session_id: 'old-ask', mode: 'ask', title: null }); await old! })
    expect(latest!.sessionId).toBe('new-maintenance')
    expect(latest!.mode).toBe('maintain')
  })

  it('切走进行中的提问后清理 busy 状态', async () => {
    let resolveQuery!: (v: unknown) => void
    apiMock.query.mockImplementation(() => new Promise((r) => { resolveQuery = r }))
    await render()
    await act(async () => { await latest!.ensureSession('ask') })
    let old: Promise<unknown>
    await act(async () => { old = latest!.ask('question') })
    expect(latest!.asking).toBe(true)
    await act(async () => { latest!.newChat() })
    await act(async () => { resolveQuery({ answer: 'old', citations: [] }); await old! })
    expect(latest!.asking).toBe(false)
  })

  it('旧提问结束不清掉更新的提问 busy 状态', async () => {
    let resolveA!: (v: unknown) => void
    let resolveB!: (v: unknown) => void
    apiMock.query
      .mockImplementationOnce(() => new Promise((r) => { resolveA = r }))
      .mockImplementationOnce(() => new Promise((r) => { resolveB = r }))
    await render()
    await act(async () => { await latest!.ensureSession('ask') })
    let old: Promise<unknown>
    let current: Promise<unknown>
    await act(async () => { old = latest!.ask('old question') })
    await act(async () => { latest!.openSession('new-ask', 'ask', []) })
    await act(async () => { current = latest!.ask('new question') })
    await act(async () => { resolveA({ answer: 'old', citations: [] }); await old! })
    expect(latest!.asking).toBe(true) // 新提问仍在进行
    await act(async () => { resolveB({ answer: 'new', citations: [] }); await current! })
    expect(latest!.asking).toBe(false)
  })
})
