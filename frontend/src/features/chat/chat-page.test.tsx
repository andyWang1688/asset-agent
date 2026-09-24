// @vitest-environment jsdom
import { vi, afterEach, beforeEach, expect, it } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
const apiMock = vi.hoisted(() => ({ createSession: vi.fn(), streamQuery: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: apiMock, errMsg: String }))
vi.mock('@/store/app-state', () => ({ useApp: () => ({ health: { knowledge_model: true } }) }))
vi.mock('@/hooks/use-maintenance', () => ({ useMaintenance: () => ({ reports: [], tasks: [] }) }))
vi.mock('@/hooks/use-submissions', () => ({ useSubmissions: () => ({}) }))
vi.mock('./message-list', () => ({ MessageList: () => null }))
vi.mock('./confirm-sheet', () => ({ ConfirmSheet: () => null }))
vi.mock('./composer', () => ({ Composer: ({ value, onChange, onSend, sendDisabled }: {
  value: string; onChange: (s: string) => void; onSend: () => void; sendDisabled: boolean
}) => <><textarea value={value} onInput={(e) => onChange(e.currentTarget.value)} readOnly />
  <button onClick={onSend} disabled={sendDisabled}>send</button></> }))
import { useChat } from '@/hooks/use-chat'
import { ChatPage } from './chat-page'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let chat: ReturnType<typeof useChat>
let finish: () => void
function Harness() { chat = useChat(); return <ChatPage chat={chat} /> }
async function input(text: string) {
  await act(async () => {
    const el = document.querySelector('textarea')!
    el.value = text
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
beforeEach(async () => {
  sessionStorage.clear()
  apiMock.createSession.mockResolvedValue({ session_id: 'a', mode: 'ask' })
  apiMock.streamQuery.mockImplementation((_q, _sid, handlers) => new Promise<void>((resolve) => {
    finish = () => { handlers.onAnswer({ answer: 'answer', citations: [] }); resolve() }
  }))
  const el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el)
  await act(async () => root.render(createElement(Harness)))
  await input('first question')
  await act(async () => document.querySelector('button')!.click())
})
afterEach(async () => { await act(async () => root.unmount()); document.body.innerHTML = ''; vi.clearAllMocks() })
it.each([false, true])('preserves a newer draft (new session: %s)', async (switchSession) => {
  if (switchSession) await act(async () => chat.newChat())
  await input('new unsent draft')
  await act(async () => finish())
  expect(document.querySelector('textarea')!.value).toBe('new unsent draft')
})
it('clears the submitted draft on success', async () => {
  await act(async () => finish())
  expect(document.querySelector('textarea')!.value).toBe('')
})
it('does not clear identical text entered in a new session', async () => {
  await act(async () => chat.newChat())
  await input('first question')
  await act(async () => finish())
  expect(document.querySelector('textarea')!.value).toBe('first question')
})
