// @vitest-environment jsdom
import { vi } from 'vitest'

vi.mock('@/lib/api', () => ({
  api: new Proxy({}, { get: () => vi.fn(async () => []) }),
  errMsg: (e: unknown) => String(e),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { AppProvider } from '@/store/app-context'
import { useChat } from '@/hooks/use-chat'
import { ChatPage } from './chat-page'

let root: Root | null = null
async function render() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const r = createRoot(container)
  root = r
  await act(async () => { r.render(createElement(AppProvider, null, createElement(Harness))) })
  await act(async () => {})
}
function Harness() {
  const chat = useChat()
  return createElement(ChatPage, { chat })
}

afterEach(() => {
  const r = root
  if (r) act(() => r.unmount())
  root = null
  document.body.innerHTML = ''
})

describe('对话模式与附件', () => {
  it('问答草稿显示只读标识且无附件', async () => {
    await render()
    expect(document.body.textContent).toContain('问答 · 只读')
    expect(document.querySelector('[aria-label="添加附件"]')).toBeNull()
  })

  it('维护草稿显示维护标识且有附件入口', async () => {
    await render()
    const maintain = [...document.querySelectorAll('button')].find((b) => b.textContent === '维护')
    expect(maintain).toBeTruthy()
    await act(async () => { maintain!.click() })
    expect(document.body.textContent).toContain('维护')
    expect(document.querySelector('[aria-label="添加附件"]')).not.toBeNull()
  })
})
