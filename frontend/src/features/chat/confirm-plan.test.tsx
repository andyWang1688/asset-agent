// @vitest-environment jsdom
import { vi, expect, it, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
const api = vi.hoisted(() => ({ reviewSubmission: vi.fn(), confirmSubmission: vi.fn(), cancelSubmission: vi.fn() }))
vi.mock('@/lib/api', () => ({ api, errMsg: (e: unknown) => String(e) }))
import { ConfirmSheet } from './confirm-sheet'
import type { ReviewResponse, SubmissionView } from '@/lib/types'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
const view: SubmissionView = { submission_id: 1, session_id: 'maintain', report_id: 1, status: 'waiting', original_name: 'notes.md', created_at: '', summary: {}, findings: [], preview: '周二读书。' }
const review: ReviewResponse = { revision: 'r', findings: [], documents: [{ id: 'document', name: '资料正文', text: '周二读书。', preview: '周二读书。', sheets: [], units: [{ id: 'document:0:5', start: 0, end: 5, text: '周二读书。', preview: '周二读书。', finding_ids: [], row: 1 }] }] }

const callbacks = { onClose: vi.fn(), onConfirmed: vi.fn(), onCancelled: vi.fn() }
async function render(v: SubmissionView | null = view) {
  if (!root) { const el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el) }
  await act(async () => root.render(createElement(ConfirmSheet, { ...callbacks, view: v, loading: false })))
  await tick()
}
async function tick() { await act(async () => { await vi.advanceTimersByTimeAsync(150) }) }
function button(text: string) { const b = [...document.querySelectorAll('button')].find((b) => b.textContent === text); expect(b, text).toBeTruthy(); return b! }
async function click(text: string) { await act(async () => button(text).click()) }
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks()
  api.reviewSubmission.mockResolvedValue(review); api.confirmSubmission.mockResolvedValue({ submission_id: 1, task_id: 1, report_id: 1 })
})
afterEach(async () => { if (root) await act(async () => root.unmount()); root = undefined as unknown as Root; document.body.innerHTML = ''; vi.useRealTimers() })
it('one confirmation submits a task and never asks for plan approval', async () => {
  await render()
  expect(api.confirmSubmission).not.toHaveBeenCalled()
  expect(document.querySelector('section[aria-label="所选内容与保存设置"]')).toBeNull()
  await click('确认并开始维护')
  expect(api.confirmSubmission).toHaveBeenCalledWith(1, {}, 'maintain', {}, undefined, [])
  expect(callbacks.onConfirmed).toHaveBeenCalledWith({ submission_id: 1, task_id: 1, report_id: 1 })
  expect(document.body.textContent).not.toContain('确认执行维护')
})
it('carries manually protected coordinates into the accepted task', async () => {
  await render()
  await act(async () => document.querySelector<HTMLButtonElement>('[data-review-unit]')!.click())
  await click('保护内容'); await tick()
  const id = 'manual:document:0:5'
  const marks = [{ source: 'document', start: 0, end: 5 }]
  expect(api.reviewSubmission).toHaveBeenLastCalledWith(1, 'maintain', { [id]: 'store' }, {}, marks)
  await click('确认并开始维护')
  expect(api.confirmSubmission).toHaveBeenLastCalledWith(1, { [id]: 'store' }, 'maintain', {}, undefined, marks)
})
it('review failure blocks planning and confirmation', async () => {
  api.reviewSubmission.mockRejectedValue(new Error('本机审查失败'))
  await render()
  expect(button('确认并开始维护').disabled).toBe(true)
  expect(document.body.textContent).toContain('本机审查失败')
  expect(api.confirmSubmission).not.toHaveBeenCalled()
})
it('discards late raw data on close', async () => {
  let resolve!: (r: ReviewResponse) => void
  api.reviewSubmission.mockImplementation(() => new Promise((r) => { resolve = r }))
  await render(); await render(null)
  await act(async () => resolve(review))
  expect(document.body.textContent).not.toContain('周二读书')
})
it('changing a name keeps focus and rejects an empty name', async () => {
  const f = { id: 'secret', source: 'document', start: 0, end: 5, name: '读书暗号', description: '', action: 'store', private_ref: '[🔒 读书暗号](private:one)' }
  api.reviewSubmission.mockResolvedValue({ ...review, findings: [f], documents: [{ ...review.documents[0], units: [{ ...review.documents[0].units[0], finding_ids: ['secret'], preview: f.private_ref }] }] })
  await render()
  await act(async () => document.querySelector<HTMLButtonElement>('[data-review-unit]')!.click())
  const input = document.getElementById('secret-name') as HTMLInputElement
  input.focus()
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, ''); input.dispatchEvent(new Event('input', { bubbles: true })) })
  expect(document.activeElement).toBe(input)
  expect(button('确认并开始维护').disabled).toBe(true)
  expect(document.body.textContent).toContain('名称不能为空')
  expect([...document.querySelectorAll('button')].some((b) => b.textContent === '确认执行维护')).toBe(false)
})
it('locks edits only while submitting the task', async () => {
  api.confirmSubmission.mockImplementation(() => new Promise(() => {}))
  await render(); await act(async () => document.querySelector<HTMLButtonElement>('[data-review-unit]')!.click())
  await click('确认并开始维护')
  expect(button('保护内容').disabled).toBe(true)
  expect(button('拒绝导入').disabled).toBe(true)
})
it('uses one directory for sheets and attached text, without separate document modes', async () => {
  const unit = review.documents[0].units[0]
  api.reviewSubmission.mockResolvedValue({ ...review, documents: [
    { ...review.documents[0], sheets: [{ name: '服务账号' }, { name: '个人资料' }], units: [
      { ...unit, id: 'sheet-one', sheet: 0, row: 2, col: 1, text: '服务原文', preview: '服务原文' },
      { ...unit, id: 'sheet-two', sheet: 1, row: 2, col: 1, text: '个人原文', preview: '个人原文' },
    ] },
    { ...review.documents[0], id: 'instruction', name: '整理要求', units: [{ ...unit, id: 'attached', text: '一起整理', preview: '一起整理' }] },
  ] })
  await render()
  const nav = document.querySelector('nav[aria-label="审查目录"]')!
  expect(nav.textContent).toBe('服务账号个人资料附带文字')
  expect(document.body.textContent).not.toContain('资料正文')
  expect(document.body.textContent).not.toContain('整理要求')
  expect(document.body.textContent).not.toContain('请核对右侧内容')
  await act(async () => document.querySelector<HTMLButtonElement>('[data-review-unit="sheet-one"]')!.click())
  expect(document.querySelector('section[aria-label="所选内容与保存设置"]')).toBeTruthy()
  await act(async () => [...nav.querySelectorAll('button')].find((b) => b.textContent === '个人资料')!.click())
  expect(document.querySelector('section[aria-label="所选内容与保存设置"]')).toBeNull()
  expect(document.querySelector('[data-review-pane="source"]')!.textContent).toContain('个人原文')
  await click('附带文字')
  expect(document.querySelector('[data-review-pane="source"]')!.textContent).toContain('一起整理')
})
it('updates only the selected repeated value after cancelling protection', async () => {
  const value = 'review-person@example.test'
  const findings = ['first', 'second'].map((id, i) => ({ id, source: 'document', start: i * 30, end: i * 30 + value.length, name: '邮箱', description: '', action: 'redact', private_ref: '[REDACTED:email]' }))
  api.reviewSubmission.mockImplementation((_id, _session, decisions: Record<string, string>) => Promise.resolve({ ...review, findings, documents: [{ ...review.documents[0], units: findings.map((f, i) => ({ id: f.id, start: f.start, end: f.end, row: i + 1, text: value, preview: decisions[f.id] === 'allow' ? value : f.private_ref, finding_ids: [f.id] })) }] }))
  await render()
  await act(async () => document.querySelector<HTMLButtonElement>('[data-review-pane="source"] [data-review-unit="first"]')!.click())
  await click('取消保护'); await tick()
  const first = document.querySelector('[data-review-pane="ai"] [data-review-unit="first"]')!
  const second = document.querySelector('[data-review-pane="ai"] [data-review-unit="second"]')!
  expect(first.textContent).toBe(value)
  expect(second.textContent).toBe('[REDACTED:email]')
  expect(second.className).toContain('bg-amber-500/25')
  expect(first.className).not.toContain('bg-amber-500/25')
})
it('edits one of four fragments at a time and keeps a cancelled fragment selected', async () => {
  const text = '地址示意\n第一段 第二段 第三段 第四段'
  const findings = ['第一段', '第二段', '第三段', '第四段'].map((value, i) => ({ id: `part-${i}`, source: 'document', start: text.indexOf(value), end: text.indexOf(value) + value.length, name: `待确认内容-${i + 1}`, description: '', action: 'store', private_ref: `[🔒 待确认内容-${i + 1}](private:part${i})` }))
  api.reviewSubmission.mockImplementation((_id, _session, decisions: Record<string, string>) => Promise.resolve({ ...review, findings: findings.map(f => ({ ...f, action: decisions[f.id] ?? f.action })), documents: [{ ...review.documents[0], sheets: [{ name: '连接资料' }], text, units: [{ id: 'multi', sheet: 0, row: 12, col: 4, start: 0, end: text.length, text, preview: '地址示意\n🔒 已保护', finding_ids: findings.map(f=>f.id) }] }] }))
  await render()
  await act(async () => document.querySelector<HTMLButtonElement>('[data-review-pane="source"] [data-review-unit="multi"]')!.click())
  expect(document.querySelectorAll('section[aria-label="所选内容与保存设置"] input')).toHaveLength(2)
  expect(document.body.textContent).toContain('片段 1 / 4')
  expect(document.querySelector('[data-review-pane="source"] [data-active-fragment="true"] > span')?.textContent).toBe('第一段')
  await click('下一片段')
  expect(document.getElementById('part-1-name')).toBeTruthy()
  expect(document.querySelector('[data-review-pane="source"] [data-active-fragment="true"] > span')?.textContent).toBe('第二段')
  await click('取消保护'); await tick()
  expect(document.body.textContent).toContain('片段 2 / 4')
  expect(button('恢复保护')).toBeTruthy()
  await click('恢复保护'); await tick()
  expect(api.reviewSubmission).toHaveBeenLastCalledWith(1, 'maintain', { 'part-1': 'store' }, {}, [])
})
it('highlights Unicode source offsets and exact safe preview spans without leaking source into AI pane', async () => {
  const value = 'private-fixture'
  const text = `😀连接信息 ${value} 尾部`
  const prefix = '😀连接信息 '
  const ref = '[🔒 待确认内容](private:pr_1234567890abcdef)'
  const preview = `${prefix}${ref} 尾部`
  const start = Array.from(prefix).length
  const finding = { id: 'unicode', source: 'document', start, end: start + value.length, name: '待确认内容', description: '', action: 'store', private_ref: ref }
  api.reviewSubmission.mockResolvedValue({ ...review, findings: [finding], documents: [{ ...review.documents[0], text, preview, sheets: [{ name: '测试' }], units: [{ id: 'unicode-cell', text, preview, start: 0, end: Array.from(text).length, row: 2, col: 1, sheet: 0, finding_ids: ['unicode'], preview_spans: [{ finding_id: 'unicode', start, end: start + Array.from(ref).length }] }] }] })
  await render()
  const cell = document.querySelector<HTMLButtonElement>('[data-review-pane="source"] [data-review-unit]')!
  expect(cell.className).toContain('overflow-hidden')
  await act(async () => cell.click())
  expect(cell.className).not.toContain('overflow-hidden')
  expect(document.querySelector('[data-review-pane="source"] [data-active-fragment="true"] > span')?.textContent).toBe(value)
  const ai = document.querySelector('[data-review-pane="ai"]')!
  expect(ai.querySelector('[data-active-fragment="true"] > span')?.textContent).toBe('🔒 待确认内容')
  expect(ai.innerHTML).not.toContain(value)
})

it('restores a legacy draft but submits it through the new single confirmation', async () => {
  const draft = { decisions: { secret: 'allow' }, edits: { secret: { name: '保存的名称' } }, manual: [] }
  await render({ ...view, draft, plan_status: 'failed' })
  expect(api.reviewSubmission).toHaveBeenLastCalledWith(1, 'maintain', draft.decisions, draft.edits, [])
  await click('确认并开始维护')
  expect(api.confirmSubmission).toHaveBeenCalledWith(1, draft.decisions, 'maintain', draft.edits, undefined, [])
  expect(callbacks.onConfirmed).toHaveBeenCalledOnce()
})
