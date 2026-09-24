// @vitest-environment jsdom
import { vi, afterEach, beforeEach, expect, it } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { Composer } from './composer'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
beforeEach(() => {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
})
afterEach(async () => {
  await act(async () => root.unmount())
  document.body.innerHTML = ''
})
async function render(mode: 'ask' | 'maintain') {
  await act(async () => root.render(createElement(Composer, {
    mode, value: '', onChange: vi.fn(), onSend: vi.fn(), sending: false,
    sendDisabled: false, fileName: null, onFileChange: vi.fn(),
  })))
}
it('维护模式可选择常见文档', async () => {
  await render('maintain')
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
  expect(input.accept.split(',')).toEqual(['.md', '.txt', '.text', '.pdf', '.xlsx', '.xls', '.csv', '.docx'])
  expect(document.querySelector('textarea')?.placeholder).toContain('PDF / Excel / Word')
})
it('问答模式仍不允许上传附件', async () => {
  await render('ask')
  expect(document.querySelector('input[type="file"]')).toBeNull()
  expect(document.querySelector('[aria-label="添加附件"]')).toBeNull()
})
