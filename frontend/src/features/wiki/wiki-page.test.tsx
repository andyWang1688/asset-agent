// @vitest-environment jsdom
import { vi, afterEach, beforeEach, expect, it } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { WikiPage } from './wiki-page'

const mocks = vi.hoisted(() => ({ pages: vi.fn(), mobile: false }))
vi.mock('@/lib/api', () => ({ api: { wikiPages: mocks.pages } }))
vi.mock('@/store/app-state', () => ({ useApp: () => ({ wikiPath: null, openPrivateRef: vi.fn() }) }))
vi.mock('@/hooks/use-is-mobile', () => ({ useIsMobile: () => mocks.mobile }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
beforeEach(() => {
  mocks.mobile = false
  mocks.pages.mockReset().mockResolvedValue([])
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
})
afterEach(async () => {
  await act(async () => root.unmount())
  document.body.innerHTML = ''
})
async function render() {
  await act(async () => root.render(createElement(WikiPage)))
}

it.each([false, true])('空库不显示目录、搜索框或空分类（移动端=%s）', async (mobile) => {
  mocks.mobile = mobile
  await render()
  expect(document.body.textContent).toContain('知识库暂无内容')
  expect(document.body.textContent).toContain('新建维护对话')
  expect(document.querySelector('aside, input, button')).toBeNull()
})

it('只有索引和日志时仍视为空库', async () => {
  mocks.pages.mockResolvedValue([{ path: 'index.md' }, { path: 'log.md' }])
  await render()
  expect(document.body.textContent).toContain('知识库暂无内容')
  expect(document.querySelector('aside')).toBeNull()
})

it('有页面时仅显示非空分类及阅读提示', async () => {
  mocks.pages.mockResolvedValue([{ path: 'projects/reading.md', title: '阅读计划' }])
  await render()
  const nav = document.querySelector('aside')!
  expect(nav.textContent).toContain('项目')
  expect(nav.textContent).toContain('阅读计划')
  for (const label of ['实体', '分析', '来源', '概念']) expect(nav.textContent).not.toContain(label)
  expect(document.body.textContent).toContain('从目录中选择知识页开始阅读。')
  expect(document.body.textContent).not.toContain('知识库暂无内容')
})

it('加载中不误报空库', async () => {
  mocks.pages.mockReturnValue(new Promise(() => {}))
  await render()
  expect(document.querySelector('[data-slot="skeleton"]')).not.toBeNull()
  expect(document.body.textContent).not.toContain('知识库暂无内容')
})

it('加载失败不误报空库', async () => {
  mocks.pages.mockRejectedValue(new Error('网络连接失败'))
  await render()
  expect(document.body.textContent).toContain('加载失败')
  expect(document.body.textContent).toContain('网络连接失败')
  expect(document.body.textContent).not.toContain('知识库暂无内容')
})
