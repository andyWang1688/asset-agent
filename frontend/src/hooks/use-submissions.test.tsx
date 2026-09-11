// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  pendingSubmissions: vi.fn(),
  submissionView: vi.fn(),
}))
vi.mock('@/lib/api', () => ({ api: apiMock, errMsg: (e: unknown) => String(e) }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useSubmissions } from './use-submissions'

let root: Root | null = null
let latest: ReturnType<typeof useSubmissions> | null = null
function Harness({ sid }: { sid: string | null }) {
  latest = useSubmissions(sid)
  return null
}
async function mount(sid: string | null) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
  await act(async () => { root!.render(createElement(Harness, { sid })) })
}

beforeEach(() => {
  apiMock.pendingSubmissions.mockReset().mockResolvedValue([])
  apiMock.submissionView.mockReset()
})
afterEach(async () => {
  if (root) await act(async () => root!.unmount())
  root = null
  latest = null
  document.body.innerHTML = ''
})

describe('待确认提交过期保护', () => {
  it('切到非维护会话后，旧确认视图请求不打开', async () => {
    let resolveView!: (v: unknown) => void
    apiMock.submissionView.mockReturnValue(new Promise((r) => { resolveView = r }))
    await mount('maintenance')
    let loading: Promise<unknown>
    await act(async () => { loading = latest!.openView(7) })
    await act(async () => { root!.render(createElement(Harness, { sid: null })) })
    await act(async () => { resolveView({ submission_id: 7, session_id: 'maintenance', findings: [] }); await loading! })
    expect(latest!.view).toBeNull()
  })
})
