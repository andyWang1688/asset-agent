// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  tasks: vi.fn(async () => [
    { id: 1, source_id: 10, session_id: 's-1', report_id: 1, status: 'pending', error: null, retries: 0, original_name: 'a.txt', created_at: '2026-09-08 12:00:00', updated_at: '' },
    { id: 2, source_id: 11, session_id: 's-2', report_id: 2, status: 'done', error: null, retries: 0, original_name: 'b.txt', created_at: '2026-09-08 12:00:00', updated_at: '' },
    { id: 3, source_id: 12, session_id: 's-3', report_id: 3, status: 'failed', error: '编译失败', retries: 0, original_name: 'c.txt', created_at: '2026-09-08 12:00:00', updated_at: '' },
  ]),
  reportView: vi.fn(async () => null),
}))
vi.mock('@/lib/api', () => ({
  api: apiMock,
  errMsg: (e: unknown) => String(e),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, describe, expect, it } from 'vitest'
import { AppProvider } from '@/store/app-context'
import { TasksPage } from './tasks-page'

let root: Root | null = null
async function render() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root!.render(createElement(AppProvider, null, createElement(TasksPage))) })
  await act(async () => {})
}

beforeEach(() => apiMock.tasks.mockClear())

describe('任务页只读', () => {
  it('只显示处理中/成功/失败，不提供重试', async () => {
    await render()
    const text = document.body.textContent || ''
    expect(text).toContain('处理中')
    expect(text).toContain('成功')
    expect(text).toContain('失败')
    // 没有重试按钮（描述文案会提到“不提供重试”，但不存在可点击的重试操作）
    const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent || '')
    expect(buttons.some((t) => t.includes('重试'))).toBe(false)
  })
})
