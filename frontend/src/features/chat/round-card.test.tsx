// @vitest-environment jsdom
import { vi, expect, it, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import type { ReportSnapshot } from '@/lib/types'
vi.mock('@/store/app-state', () => ({ useApp: () => ({ setTab: vi.fn() }) }))
import { RoundCard } from './chat-page'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.innerHTML = '' })
it('keeps the summary filename compact, exposes the full name on hover and collapses text', async () => {
  const name = '核对重复资源与密码引用.txt'
  const preview = '一段很长但已脱敏的正文。'.repeat(100)
  const el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el)
  await act(async () => root.render(createElement(RoundCard, { report: {
    original_name: name, preview, status: 'confirmed', created_at: '2026-09-23 07:50:00',
  } as ReportSnapshot })))
  const title = document.querySelector('b')!
  expect(title.textContent).toBe(name)
  expect(title.title).toBe(name)
  expect(title.className).toContain('truncate')
  expect(document.body.textContent).not.toContain(preview)
  const button = [...document.querySelectorAll('button')].find((b) => b.textContent === '查看脱敏内容')!
  await act(async () => button.click())
  expect(document.querySelector('pre')?.textContent).toBe(preview)
  expect(document.querySelector('pre')?.className).toContain('max-h-56')
})
