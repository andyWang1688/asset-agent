// @vitest-environment jsdom
import { vi, afterEach, expect, it } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { WikiDoc } from '@/lib/types'
const apiMock = vi.hoisted(() => ({ wikiPages: vi.fn().mockResolvedValue([]), wikiPage: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: apiMock }))
import { useWiki } from './use-wiki'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let wiki: ReturnType<typeof useWiki>
function Harness() { wiki = useWiki(); return null }
afterEach(async () => { await act(async () => root.unmount()); document.body.innerHTML = ''; vi.clearAllMocks() })

it.each(['success', 'error'])('ignores stale page %s and keeps the latest page loading', async (outcome) => {
  let resolveA!: (doc: WikiDoc) => void
  let rejectA!: (error: Error) => void
  let resolveB!: (doc: WikiDoc) => void
  apiMock.wikiPage
    .mockImplementationOnce(() => new Promise((resolve, reject) => { resolveA = resolve; rejectA = reject }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve }))
  const el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el)
  await act(async () => root.render(createElement(Harness)))
  let a!: Promise<void>, b!: Promise<void>
  await act(async () => { a = wiki.open('projects/a.md') })
  await act(async () => { b = wiki.open('projects/b.md') })
  await act(async () => {
    if (outcome === 'success') resolveA({ path: 'projects/a.md', content: 'A' })
    else rejectA(new Error('A failed'))
    await a
  })
  expect(wiki.loading).toBe(true)
  expect(wiki.error).toBeNull()
  expect(wiki.doc).toBeNull()
  await act(async () => { resolveB({ path: 'projects/b.md', content: 'B' }); await b })
  expect(wiki.path).toBe('projects/b.md')
  expect(wiki.doc?.path).toBe('projects/b.md')
})

it('does not overwrite B when A completes last', async () => {
  let resolveA!: (doc: WikiDoc) => void
  apiMock.wikiPage.mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve }))
    .mockResolvedValueOnce({ path: 'projects/b.md', title: 'B', content: 'B' })
  const el = document.createElement('div'); document.body.appendChild(el); root = createRoot(el)
  await act(async () => root.render(createElement(Harness)))
  let a!: Promise<void>
  await act(async () => { a = wiki.open('projects/a.md') })
  await act(async () => { await wiki.open('projects/b.md') })
  await act(async () => { resolveA({ path: 'projects/a.md', content: 'A' }); await a })
  expect(wiki.path).toBe(wiki.doc?.path)
})
