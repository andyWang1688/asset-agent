// @vitest-environment jsdom
import { vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: {
    createSession: vi.fn(),
    streamQuery: vi.fn(),
    listSessions: vi.fn(),
    chatHistory: vi.fn(),
    setSessionTitle: vi.fn(),
    setSessionPin: vi.fn(),
    deleteSession: vi.fn(),
  },
  app: { tab: 'chat', setTab: vi.fn(), navigateSettings: vi.fn() },
}))

vi.mock('@/lib/api', () => ({ api: mocks.api, errMsg: (e: unknown) => String(e) }))
vi.mock('@/store/app-state', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/store/app-state')>()),
  useApp: () => mocks.app,
}))
vi.mock('@/hooks/use-tasks', () => ({ useTasks: () => ({ attention: [] }) }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import type { ChatEntry, SessionInfo } from '@/lib/types'
import { useChat } from '@/hooks/use-chat'
import { SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppSidebar } from './app-sidebar'

let root: Root | null = null
let chat: ReturnType<typeof useChat> | null = null

function Harness() {
  const c = useChat()
  chat = c
  return createElement(
    TooltipProvider,
    null,
    createElement(SidebarProvider, null, createElement(AppSidebar, { chat: c })),
  )
}

async function render() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
  await act(async () => {
    root!.render(createElement(Harness))
  })
}

function session(id: string, title: string, mode: SessionInfo['mode'] = 'ask'): SessionInfo {
  return { session_id: id, mode, title, pinned: false, created_at: '2026-09-17 10:00:00' }
}

function entry(id: number, sessionId: string, question: string, answer: string): ChatEntry {
  return {
    id,
    session_id: sessionId,
    question,
    answer,
    citations: [],
    title: null,
    pinned: false,
    mode: 'ask',
    created_at: '2026-09-17 10:00:01',
  }
}

function historyItem(title: string): HTMLButtonElement {
  const el = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes(title))
  expect(el, `历史项「${title}」`).toBeTruthy()
  return el as HTMLButtonElement
}

interface StreamHandlersStub {
  onAnswer?: (r: { answer: string; citations: string[] }) => void
  onError?: (message: string) => void
}

beforeEach(() => {
  chat = null
  sessionStorage.clear()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  })
  mocks.api.createSession.mockReset()
  mocks.api.streamQuery.mockReset()
  mocks.api.listSessions.mockReset().mockResolvedValue([])
  mocks.api.chatHistory.mockReset().mockResolvedValue([])
  mocks.api.setSessionTitle.mockReset()
  mocks.api.setSessionPin.mockReset()
  mocks.api.deleteSession.mockReset()
})

afterEach(async () => {
  if (root) await act(async () => root!.unmount())
  root = null
  chat = null
  document.body.innerHTML = ''
  sessionStorage.clear()
})

it('回答完成后点击当前历史会话，界面仍保留这段问答', async () => {
  let sessions: SessionInfo[] = []
  let rows: ChatEntry[] = []
  let finish!: () => void
  let handlers: StreamHandlersStub = {}
  mocks.api.listSessions.mockImplementation(async () => sessions)
  mocks.api.chatHistory.mockImplementation(async () => rows)
  mocks.api.createSession.mockImplementation(async (mode: SessionInfo['mode']) => {
    const s = session('s-1', '验收会话', mode)
    sessions = [s]
    return s
  })
  mocks.api.streamQuery.mockImplementation((_q: string, _sid: string, h: StreamHandlersStub) => {
    handlers = h
    return new Promise<void>((resolve) => {
      finish = resolve
    })
  })

  await render()
  let pending: Promise<unknown> | null = null
  await act(async () => {
    pending = chat!.ask('蓝鲸读书项目什么时候开始？')
  })
  expect(chat!.messages).toHaveLength(1)

  await act(async () => {
    rows = [entry(1, 's-1', '蓝鲸读书项目什么时候开始？', '周二九点半')]
    handlers.onAnswer?.({ answer: '周二九点半', citations: [] })
    finish()
    await pending
  })
  expect(chat!.messages[0].a).toBe('周二九点半')

  await act(async () => historyItem('验收会话').click())
  expect(chat!.messages).toHaveLength(1)
  expect(chat!.messages[0].a).toBe('周二九点半')
})

it('从历史切换到其他会话时按后端记录恢复问答', async () => {
  const sessions = [session('s-a', '会话 A'), session('s-b', '会话 B')]
  const rows = [entry(1, 's-a', 'A 的问题', 'A 的答案'), entry(2, 's-b', 'B 的问题', 'B 的答案')]
  mocks.api.listSessions.mockImplementation(async () => sessions)
  mocks.api.chatHistory.mockImplementation(async () => rows)

  await render()
  await act(async () => historyItem('会话 B').click())
  expect(chat!.messages).toHaveLength(1)
  expect(chat!.messages[0].q).toBe('B 的问题')
  expect(chat!.messages[0].a).toBe('B 的答案')

  await act(async () => historyItem('会话 A').click())
  expect(chat!.messages).toHaveLength(1)
  expect(chat!.messages[0].q).toBe('A 的问题')
})
