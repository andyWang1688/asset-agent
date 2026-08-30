// @vitest-environment jsdom
import { vi } from 'vitest'

// 隔离网络：任意 api 方法返回空数据
vi.mock('@/lib/api', () => ({
  api: new Proxy({}, { get: () => vi.fn(async () => []) }),
  errMsg: (e: unknown) => String(e),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// jsdom 无 matchMedia：补最小实现
window.matchMedia = ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { AppProvider } from '@/store/app-context'
import { useChat } from '@/hooks/use-chat'
import { ChatPage } from './chat-page'
import { TasksPage } from '@/features/tasks/tasks-page'

const roots: Root[] = []
async function render(node: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => {
    root.render(createElement(AppProvider, null, node))
  })
  await act(async () => {})
}
function Harness() {
  const chat = useChat()
  return <ChatPage active chat={chat} />
}
afterEach(() => {
  while (roots.length) {
    const root = roots.pop()
    if (root) act(() => root.unmount())
  }
  document.body.innerHTML = ''
})

describe('对话历史归属', () => {
  it('聊天页：历史按钮在内容卡右上角，可打开面板', async () => {
    await render(<Harness />)
    const btn = document.querySelector('[aria-label="对话历史"]')
    expect(btn).not.toBeNull()
    await act(async () => {
      ;(btn as HTMLButtonElement).click()
    })
    const panel = [...document.querySelectorAll('aside')].find((a) => a.textContent?.includes('对话历史'))
    expect(panel).not.toBeUndefined()
    expect(panel?.getAttribute('aria-hidden')).toBe('false')
  })

  it('任务页：不存在任何历史入口', async () => {
    await render(<TasksPage />)
    expect(document.querySelector('[aria-label="对话历史"]')).toBeNull()
  })
})
