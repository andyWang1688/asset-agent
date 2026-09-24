// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  createSession: vi.fn(),
  streamQuery: vi.fn(),
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

interface StreamHandlersStub {
  onReasoning?: (text: string) => void
  onAction?: (action: { action: string; path?: string; query?: string }) => void
  onRetry?: () => void
  onAnswer?: (r: { answer: string; citations: string[] }) => void
  onError?: (message: string) => void
}

beforeEach(() => {
  apiMock.createSession.mockReset()
  apiMock.streamQuery.mockReset()
  apiMock.chatHistory.mockReset()
  apiMock.listSessions.mockReset()
  apiMock.listSessions.mockResolvedValue([])
  sessionStorage.clear()
  apiMock.createSession.mockImplementation(async (mode: string) => ({ session_id: 's-1', mode, title: null, pinned: false, created_at: '' }))
  apiMock.streamQuery.mockImplementation(async (_q: string, _sid: string, h: StreamHandlersStub) => {
    h.onAnswer?.({ answer: 'ok', citations: [] })
  })
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
    let handlers: StreamHandlersStub | undefined
    apiMock.streamQuery.mockImplementation((_q: string, _sid: string, h: StreamHandlersStub) => {
      handlers = h
      return new Promise((r) => { resolveQuery = r })
    })
    await render()
    await act(async () => { await latest!.ensureSession('ask') })
    let old: Promise<unknown>
    await act(async () => { old = latest!.ask('question') })
    expect(latest!.asking).toBe(true)
    await act(async () => { latest!.newChat() })
    await act(async () => {
      handlers?.onAnswer?.({ answer: 'old', citations: [] })
      resolveQuery(undefined)
      await old!
    })
    expect(latest!.asking).toBe(false)
  })

  it('旧提问结束不清掉更新的提问 busy 状态', async () => {
    let resolveA!: (v: unknown) => void
    let resolveB!: (v: unknown) => void
    let handlersA: StreamHandlersStub | undefined
    let handlersB: StreamHandlersStub | undefined
    apiMock.streamQuery
      .mockImplementationOnce((_q: string, _sid: string, h: StreamHandlersStub) => {
        handlersA = h
        return new Promise((r) => { resolveA = r })
      })
      .mockImplementationOnce((_q: string, _sid: string, h: StreamHandlersStub) => {
        handlersB = h
        return new Promise((r) => { resolveB = r })
      })
    await render()
    await act(async () => { await latest!.ensureSession('ask') })
    let old: Promise<unknown>
    let current: Promise<unknown>
    await act(async () => { old = latest!.ask('old question') })
    await act(async () => { latest!.openSession('new-ask', 'ask', []) })
    await act(async () => { current = latest!.ask('new question') })
    await act(async () => {
      handlersA?.onAnswer?.({ answer: 'old', citations: [] })
      resolveA(undefined)
      await old!
    })
    expect(latest!.asking).toBe(true) // 新提问仍在进行
    await act(async () => {
      handlersB?.onAnswer?.({ answer: 'new', citations: [] })
      resolveB(undefined)
      await current!
    })
    expect(latest!.asking).toBe(false)
  })

  it('流式推理与工具动作按顺序累积为思考轨迹', async () => {
    apiMock.streamQuery.mockImplementation(async (_q: string, _sid: string, h: StreamHandlersStub) => {
      h.onAction?.({ action: 'read', path: 'projects/demo.md' })
      h.onReasoning?.('先读')
      h.onReasoning?.('页面')
      h.onRetry?.()
      h.onAnswer?.({ answer: 'ok', citations: [] })
    })
    await render()
    await act(async () => { const r = await latest!.ask('问题'); expect(r).toBeNull() })
    const last = latest!.messages[latest!.messages.length - 1]
    expect(last.pending).toBe(false)
    expect(last.trace).toEqual([
      { kind: 'action', action: 'read', path: 'projects/demo.md' },
      { kind: 'reasoning', text: '先读页面' },
      { kind: 'action', action: 'retry' },
    ])
    expect(last.thinkingMs).toBeTypeOf('number')
  })
})

it('点击正在回答的当前会话不会丢弃流式消息', async () => {
  let finish!: () => void
  let handlers!: StreamHandlersStub
  apiMock.streamQuery.mockImplementation((_q: string, _sid: string, h: StreamHandlersStub) => {
    handlers = h
    return new Promise<void>((resolve) => { finish = resolve })
  })
  await render()
  await act(async () => { await latest!.ensureSession('ask') })
  let asking!: Promise<unknown>
  await act(async () => { asking = latest!.ask('进行中的问题') })
  await act(async () => { await latest!.openSessionById('s-1') })
  expect(latest!.asking).toBe(true)
  expect(latest!.messages[0].q).toBe('进行中的问题')
  await act(async () => { handlers.onAnswer?.({ answer: '回答完成', citations: [] }); finish(); await asking })
  expect(latest!.messages[0].a).toBe('回答完成')
})

it('历史水合期间禁止按旧会话模式提交', async () => {
  let resolve!: (rows: unknown[]) => void
  apiMock.listSessions.mockImplementation(() => new Promise((r) => { resolve = r }))
  await render()
  let opened!: Promise<void>
  await act(async () => { opened = latest!.openSessionById('history-maintain') })
  expect(latest!.hydrating).toBe(true)
  await expect(latest!.ensureSession('ask')).rejects.toThrow('会话正在恢复')
  await act(async () => { resolve([{ session_id: 'history-maintain', mode: 'maintain' }]); await opened })
  expect(latest!.mode).toBe('maintain')
  expect(latest!.hydrating).toBe(false)
})
