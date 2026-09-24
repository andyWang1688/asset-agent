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
    sendDisabled: false, files: [], onFileChange: vi.fn(),
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
it('维护可批量添加附件并逐个移除', async () => {
  const files = [new File(['first'], 'one.txt'), new File(['second'], 'two.pdf')]
  const onFileChange = vi.fn()
  await act(async () => root.render(createElement(Composer, {
    mode: 'maintain', value: '', onChange: vi.fn(), onSend: vi.fn(), sending: false,
    sendDisabled: false, files, onFileChange,
  })))
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
  expect(input.multiple).toBe(true)
  expect(document.body.textContent).toContain('one.txt')
  expect(document.body.textContent).toContain('two.pdf')
  await act(async () => (document.querySelector('[aria-label="移除 one.txt"]') as HTMLButtonElement).click())
  expect(onFileChange).toHaveBeenLastCalledWith([files[1]])
  const third = new File(['third'], 'three.docx')
  Object.defineProperty(input, 'files', { value: [third] })
  await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
  expect(onFileChange).toHaveBeenLastCalledWith([...files, third])
})
