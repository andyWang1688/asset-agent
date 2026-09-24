// @vitest-environment jsdom
import { vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  reports: vi.fn(),
  tasks: vi.fn(),
}))
vi.mock('@/lib/api', () => ({ api: apiMock, errMsg: (e: unknown) => String(e) }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useMaintenance } from './use-maintenance'

let root: Root | null = null
let latest: ReturnType<typeof useMaintenance> | null = null
function Harness({ sid }: { sid: string }) {
  latest = useMaintenance(sid)
  return null
}
async function mount(sid: string) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
  await act(async () => { root!.render(createElement(Harness, { sid })) })
}

beforeEach(() => {
  apiMock.reports.mockReset()
  apiMock.tasks.mockReset()
})
afterEach(async () => {
  if (root) await act(async () => root!.unmount())
  root = null
  latest = null
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('维护聚合过期保护与轮询', () => {
  it('旧会话的 fetch 不覆盖新会话报告', async () => {
    let resolveA!: (v: unknown) => void
    apiMock.reports.mockImplementation((sid: string) => sid === 'a' ? new Promise((r) => { resolveA = r }) : Promise.resolve([{ id: 2, session_id: 'b' }]))
    apiMock.tasks.mockResolvedValue([])
    await mount('a')
    await act(async () => { root!.render(createElement(Harness, { sid: 'b' })) })
    await act(async () => { resolveA([{ id: 1, session_id: 'a' }]) })
    expect(latest!.reports.map((r) => r.session_id)).toEqual(['b'])
  })

  it('活动任务轮询后反映完成', async () => {
    vi.useFakeTimers()
    let status = 'pending'
    apiMock.reports.mockResolvedValue([{ id: 1, session_id: 'a', status: 'auto' }])
    apiMock.tasks.mockImplementation(async () => [{ id: 1, session_id: 'a', report_id: 1, status }])
    await mount('a')
    status = 'done'
    await act(async () => { await vi.advanceTimersByTimeAsync(12000) })
    expect(latest!.tasks[0]?.status).toBe('done')
  })

  it('切换会话时先清空旧数据再等待新数据', async () => {
    let resolveB!: (v: unknown) => void
    apiMock.reports.mockImplementation((sid: string) => sid === 'a' ? Promise.resolve([{ id: 1, session_id: 'a' }]) : new Promise((r) => { resolveB = r }))
    apiMock.tasks.mockResolvedValue([])
    await mount('a')
    expect(latest!.reports).toHaveLength(1)
    await act(async () => { root!.render(createElement(Harness, { sid: 'b' })) })
    expect(latest!.reports).toEqual([]) // 新数据未到前不残留旧数据
    await act(async () => { resolveB([]) })
  })
})

it('后台计划无需维护任务也持续轮询，完成后停止', async () => {
  vi.useFakeTimers()
  let status = 'queued'
  apiMock.reports.mockImplementation(async () => [{ id: 1, session_id: 'a', status: 'pending', plan_status: status }])
  apiMock.tasks.mockResolvedValue([])
  await mount('a')
  status = 'generating'
  await act(async () => { await vi.advanceTimersByTimeAsync(2500) })
  expect(latest!.reports[0].plan_status).toBe('generating')
  status = 'ready'
  await act(async () => { await vi.advanceTimersByTimeAsync(2500) })
  expect(latest!.reports[0].plan_status).toBe('ready')
  const calls = apiMock.reports.mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(apiMock.reports).toHaveBeenCalledTimes(calls)
})
