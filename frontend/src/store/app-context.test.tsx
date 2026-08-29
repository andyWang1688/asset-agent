// @vitest-environment jsdom
import { vi } from 'vitest'

// 隔离网络：Provider 挂载时会拉取 health
vi.mock('@/lib/api', () => ({
  api: { health: vi.fn(async () => null) },
  errMsg: (e: unknown) => String(e),
}))

// 让 React 的 act() 在 jsdom 环境生效，消除 act 警告
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { AppProvider } from './app-context'
import { useApp, type AppState } from './app-state'

let state: AppState | null = null
function Probe() {
  state = useApp()
  return null
}

const roots: Root[] = []
async function mount(url: string) {
  window.history.pushState(null, '', url)
  const root = createRoot(document.createElement('div'))
  roots.push(root)
  await act(async () => {
    root.render(createElement(AppProvider, null, createElement(Probe) as ReactNode))
  })
  // 冲刷挂载 effect 的异步收尾（health 等），避免 act 警告
  await act(async () => {})
  if (!state) throw new Error('probe 未渲染')
}
/** context 值每次渲染都会换新对象，断言前必须取最新快照 */
const current = () => {
  if (!state) throw new Error('probe 未渲染')
  return state
}
afterEach(() => {
  while (roots.length) {
    const root = roots.pop()
    if (root) act(() => root.unmount())
  }
  state = null
})

describe('路由单一来源', () => {
  it('深链恢复模块与二级标签', async () => {
    await mount('/settings/security#keywords')
    const s = current()
    expect(s.tab).toBe('settings')
    expect(s.settingsRoute).toBe('security')
    expect(s.securityTab).toBe('keywords')
  })

  it('navigateSettings 同步 URL 与状态', async () => {
    await mount('/')
    await act(async () => { current().navigateSettings('retrieval') })
    const s = current()
    expect(window.location.pathname).toBe('/settings/retrieval')
    expect(s.settingsRoute).toBe('retrieval')
    expect(s.tab).toBe('settings')
  })

  it('navigateSettings 进入安全策略时二级标签回落正则', async () => {
    await mount('/settings/security#entropy')
    await act(async () => { current().navigateSettings('models') })
    await act(async () => { current().navigateSettings('security') })
    const s = current()
    expect(window.location.hash).toBe('#regex')
    expect(s.securityTab).toBe('regex')
  })

  it('setSecurityTab 只改写 hash 不产生历史', async () => {
    await mount('/settings/security')
    const before = window.history.length
    await act(async () => { current().setSecurityTab('entropy') })
    const s = current()
    expect(window.location.hash).toBe('#entropy')
    expect(s.securityTab).toBe('entropy')
    expect(window.history.length).toBe(before)
  })

  it('popstate 同步状态', async () => {
    await mount('/')
    await act(async () => {
      window.history.pushState(null, '', '/settings/events')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    const s = current()
    expect(s.tab).toBe('settings')
    expect(s.settingsRoute).toBe('events')
  })

  it('setTab 离开设置时回到根路径', async () => {
    await mount('/settings/models')
    await act(async () => { current().setTab('wiki') })
    const s = current()
    expect(window.location.pathname).toBe('/wiki')
    expect(s.tab).toBe('wiki')
  })

  it('深链 /wiki 与 /tasks 恢复对应页面', async () => {
    await mount('/wiki')
    expect(current().tab).toBe('wiki')
    await mount('/tasks')
    expect(current().tab).toBe('tasks')
  })

  it('setTab 为 wiki/tasks 写入各自 URL', async () => {
    await mount('/')
    await act(async () => { current().setTab('tasks') })
    expect(window.location.pathname).toBe('/tasks')
    await act(async () => { current().setTab('chat') })
    expect(window.location.pathname).toBe('/')
  })

  it('popstate 回到 /wiki 时同步 tab', async () => {
    await mount('/wiki')
    await act(async () => { current().setTab('chat') })
    await act(async () => {
      window.history.pushState(null, '', '/wiki')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(current().tab).toBe('wiki')
  })
})
