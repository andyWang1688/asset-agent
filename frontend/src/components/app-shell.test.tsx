// @vitest-environment jsdom
import { vi } from 'vitest'

vi.mock('@/lib/api', () => ({
  api: {
    health: vi.fn(async () => null),
    tasks: vi.fn(async () => []),
    chatHistory: vi.fn(async () => []),
  },
  errMsg: (e: unknown) => String(e),
}))

// 让 React 的 act() 在 jsdom 环境生效
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { AppShell } from './app-shell'
import { AppProvider } from '@/store/app-context'

const roots: Root[] = []
const stubMatchMedia = (mobile: boolean) => {
  window.matchMedia = ((query: string) => ({
    matches: mobile && /max-width: (820|900)px/.test(query),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

async function render(mobile: boolean) {
  stubMatchMedia(mobile)
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => {
    root.render(
      createElement(
        AppProvider,
        null,
        createElement(
          AppShell,
          { onNavigate: () => undefined, children: createElement('div', null, 'content') },
        ),
      ),
    )
  })
  await act(async () => {})
}
afterEach(() => {
  while (roots.length) {
    const root = roots.pop()
    if (root) act(() => root.unmount())
  }
  document.body.innerHTML = ''
})

describe('外壳结构', () => {
  it('桌面无顶栏：品牌与折叠控件归侧栏，历史浮动在内容区', async () => {
    await render(false)
    expect(document.querySelector('header')).toBeNull()
    expect(document.body.textContent).toContain('资产 Agent')
    expect(document.querySelector('[aria-label="收起侧栏"]')).not.toBeNull()
    // 外壳不拥有对话历史：任何历史入口都不应出现在 shell 层
    expect(document.querySelector('[aria-label="对话历史"]')).toBeNull()
    expect(document.querySelector('[data-sidebar="edge"] [role="separator"]')).not.toBeNull()
  })

  it('移动端：汉堡打开一级菜单 Sheet，历史留在标题栏右侧', async () => {
    await render(true)
    expect(document.querySelector('header')).not.toBeNull()
    expect(document.querySelector('[aria-label="对话历史"]')).toBeNull()
    expect(document.querySelector('nav.fixed')).toBeNull()
    const burger = document.querySelector('header [aria-label="打开一级菜单"]')
    expect(burger).not.toBeNull()
    await act(async () => {
      ;(burger as HTMLButtonElement).click()
    })
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  })
})
