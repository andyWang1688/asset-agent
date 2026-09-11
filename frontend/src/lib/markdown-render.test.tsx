// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Markdown } from './markdown'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
async function render(content: string, onWikiLink?: (p: string) => void, onPrivateRef?: (r: string) => void) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const r = createRoot(el)
  root = r
  await act(async () => { r.render(createElement(Markdown, { content, onWikiLink, onPrivateRef })) })
  return el
}

afterEach(() => {
  const r = root
  if (r) act(() => r.unmount())
  root = null
  document.body.innerHTML = ''
})

describe('Markdown 内部链接', () => {
  it('wiki 链接走应用动作不外跳', async () => {
    const onWikiLink = vi.fn()
    const el = await render('见 [[concepts/a.md|概念 A]]', onWikiLink)
    const link = el.querySelector('a.wikilink') as HTMLAnchorElement
    expect(link).not.toBeNull()
    expect(link.getAttribute('href')).toBe('#')
    await act(async () => { link.click() })
    expect(onWikiLink).toHaveBeenCalledWith('concepts/a.md')
  })

  it('private 链接走应用动作不读取原值', async () => {
    const onPrivateRef = vi.fn()
    const el = await render('[🔒 password](private:pr_0000000000000000)', undefined, onPrivateRef)
    const btn = el.querySelector('button.private-ref') as HTMLButtonElement
    expect(btn).not.toBeNull()
    await act(async () => { btn.click() })
    expect(onPrivateRef).toHaveBeenCalledWith('pr_0000000000000000')
  })

  it('危险协议仍被拦截', async () => {
    const el = await render('[x](javascript:alert(1))')
    const link = el.querySelector('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('#')
  })
})
