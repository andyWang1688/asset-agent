// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  confirmSubmission: vi.fn(async (_id: number, _d: Record<string, string>, _sid: string, _e: Record<string, Record<string, string | undefined>>, _p?: string) => ({ source_id: 1, task_id: 2, secrets: [], secrets_count: 0 })),
  cancelSubmission: vi.fn(async () => ({ cancelled: true })),
}))
vi.mock('@/lib/api', () => ({
  api: apiMock,
  errMsg: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, describe, expect, it } from 'vitest'
import { ConfirmSheet } from './confirm-sheet'
import type { SubmissionView } from '@/lib/types'

function view(): SubmissionView {
  return {
    submission_id: 7,
    status: 'waiting',
    session_id: 'session-maintain-1',
    report_id: 3,
    original_name: 'pasted.txt',
    created_at: '2026-09-08 12:00:00',
    summary: { credential: 1, pii: 0, unknown_suspect: 0 },
    findings: [
      {
        id: 'regex:key_value_secret:0:20',
        kind: 'credential',
        rule: 'key_value_secret',
        confidence: 0.9,
        evidence: '规则 key_value_secret 命中',
        suggested_action: 'store',
        allowed_actions: ['store', 'redact', 'allow'],
        detector: 'regex',
        context: '⟨已掩码⟩',
        name: 'password',
        description: '规则 key_value_secret 命中',
        source: 'pasted.txt',
        ref_id: 'pr_abc123',
        private_ref: '[🔒 password](private:pr_abc123)',
        vault: { kind: 'login', name: 'password', field_name: '' },
      },
    ],
    preview: '[🔒 password](private:pr_abc123)',
  }
}

let root: Root | null = null
async function render(v: SubmissionView) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root!.render(createElement(ConfirmSheet, { view: v, loading: false, onClose: () => {}, onConfirmed: () => {}, onCancelled: () => {} }))
  })
}

beforeEach(() => {
  apiMock.confirmSubmission.mockClear()
})

describe('确认闸门', () => {
  it('确认发送 session_id、decisions 与 edits', async () => {
    await render(view())
    const agree = [...document.querySelectorAll('button')].find((b) => b.textContent === '同意')
    expect(agree).toBeTruthy()
    await act(async () => { agree!.click() })
    expect(apiMock.confirmSubmission).toHaveBeenCalledTimes(1)
    const [id, decisions, sessionId, edits] = apiMock.confirmSubmission.mock.calls[0]
    expect(id).toBe(7)
    expect(sessionId).toBe('session-maintain-1')
    expect(decisions).toEqual({ 'regex:key_value_secret:0:20': 'store' })
    // 未编辑任何字段时 edits 为空对象（不改写默认，避免把 rule-hash 默认名当编辑重扫）
    expect(edits).toEqual({})
  })

  it('编辑预览后点“完成修改”再确认仍提交编辑后的预览', async () => {
    await render(view())
    const click = async (text: string) => {
      const b = [...document.querySelectorAll('button')].find((x) => x.textContent === text)
      expect(b).toBeTruthy()
      await act(async () => { b!.click() })
    }
    await click('按我说的做')
    await click('编辑预览')
    const area = document.querySelector('textarea')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, 'Edited safe content')
      area.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click('完成修改')
    await click('同意')
    expect(apiMock.confirmSubmission.mock.calls[0][4]).toBe('Edited safe content')
  })

  it('改动字段后确认发送对应 edits', async () => {
    await render(view())
    const click = async (text: string) => {
      const b = [...document.querySelectorAll('button')].find((x) => x.textContent === text)
      expect(b).toBeTruthy()
      await act(async () => { b!.click() })
    }
    await click('按我说的做')
    // 展开第一个 FindingCard 后修改可读名称
    const trigger = [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('password'))
    expect(trigger).toBeTruthy()
    await act(async () => { trigger!.click() })
    const nameInput = [...document.querySelectorAll('input')].find((i) => (i as HTMLInputElement).value === 'password') as HTMLInputElement
    expect(nameInput).toBeTruthy()
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(nameInput, '生产库密码')
      nameInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click('同意')
    const edits = apiMock.confirmSubmission.mock.calls[0][3]
    expect(edits['regex:key_value_secret:0:20']).toMatchObject({ name: '生产库密码' })
  })
})
