// @vitest-environment jsdom
import { vi, it, expect, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import type { TaskRow, WikiPage } from '@/lib/types'

const state = vi.hoisted(() => ({
  rows: [] as TaskRow[],
  width: 1280,
  reportView: vi.fn(async () => ({ status: 'pending', entries: [] })),
  wikiPages: vi.fn<() => Promise<WikiPage[]>>(),
  wikiPage: vi.fn(),
  openWikiDoc: vi.fn(),
  requestOpenSession: vi.fn(),
}))
vi.mock('@/hooks/use-tasks', () => ({ useTasks: () => ({ rows: state.rows, load: vi.fn(), error: false }) }))
vi.mock('@/hooks/use-is-mobile', () => ({ useIsMobile: (breakpoint: number) => state.width <= breakpoint }))
vi.mock('@/store/app-state', () => ({ useApp: () => ({ requestOpenSession: state.requestOpenSession, openWikiDoc: state.openWikiDoc }) }))
vi.mock('@/lib/api', () => ({ api: { reportView: state.reportView, wikiPages: state.wikiPages, wikiPage: state.wikiPage } }))
import { TasksPage } from './tasks-page'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function task(overrides: Partial<TaskRow> = {}): TaskRow {
  return {
    id: 1, source_id: null, report_id: 1, session_id: 'maintenance-session-id',
    status: 'done', original_name: 'fixture.xlsx', retries: 0,
    created_at: '2026-09-23 10:00:00', updated_at: '2026-09-23 10:00:01', error: null,
    result: { changes: ['sources/fixture.md'], conflicts: [{ note: '测试资料存在冲突', between: ['sources/fixture.md'] }] },
    ...overrides,
  }
}

let root: ReturnType<typeof createRoot>
beforeEach(() => {
  vi.resetAllMocks()
  state.width = 1280
  state.rows = [task()]
  state.wikiPages.mockResolvedValue([{ path: 'sources/fixture.md', title: '测试资料' }])
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
})
afterEach(async () => {
  await act(async () => root.unmount())
  document.body.innerHTML = ''
})

async function render() {
  await act(async () => root.render(createElement(TasksPage)))
}

function toggle(id = 1) {
  return document.querySelector<HTMLButtonElement>(`button[aria-controls="task-details-${id}"]`)!
}

async function expand(id = 1) {
  if (toggle(id).getAttribute('aria-expanded') !== 'true') await act(async () => toggle(id).click())
  return document.querySelector<HTMLElement>(`#task-details-${id} section[aria-label="任务详情"]`)!
}

it('shows an accepted source-less task and its real phase, including planning failure', async () => {
  for (const [status, label] of [['planning_pending', '等待处理'], ['planning', '生成维护计划'], ['drafting', '编写 Wiki 页面'], ['saving', '保存资料与敏感信息'], ['failed', '模型输出截断']]) {
    state.rows = [task({ status, error: status === 'failed' ? '模型输出截断' : null })]
    await render()
    expect(document.body.textContent).toContain('全部 1')
    expect(document.body.textContent).toContain('fixture.xlsx')
    expect(document.body.textContent).toContain(label)
    expect(document.body.textContent).not.toContain('继续审查')
  }
})

it.each(['xlsx', 'docx', 'pdf', 'txt'])('task details for %s show results only and never fetch reports', async (ext) => {
  for (const status of ['planning', 'done', 'failed'] as const) {
    state.rows = [task({ status, original_name: `fixture.${ext}`, error: status === 'failed' ? '模型输出截断' : null })]
    await render()
    const detail = await expand()
    const statusLabel = { planning: '处理中', done: '成功', failed: '失败' }[status]
    expect(toggle().closest('tr')?.textContent).toContain(`fixture.${ext}`)
    expect(toggle().textContent).toContain(statusLabel)
    expect(detail.querySelector('header')).toBeNull()
    expect(detail.textContent).not.toContain(`fixture.${ext}`)
    expect([...detail.querySelectorAll('span')].filter((span) => span.textContent === statusLabel)).toHaveLength(0)
    if (status === 'planning') expect(detail.querySelector('p[aria-label="当前阶段"]')?.textContent).toBe('生成维护计划')
    else expect(detail.querySelector('p[aria-label="当前阶段"]')).toBeNull()
    expect(detail.textContent).toContain('更新页面')
    expect(detail.textContent).toContain('待核对事项')
    expect(detail.textContent).toContain('测试资料存在冲突')
    if (status === 'failed') expect(detail.querySelector('[role="alert"]')?.textContent).toContain('模型输出截断')
    for (const label of ['资料回看', '脱敏报告', '报告条目', '附带文字', 'maintenance-session-id']) expect(document.body.textContent).not.toContain(label)
    expect(state.reportView).not.toHaveBeenCalled()
    expect(state.wikiPage).not.toHaveBeenCalled()
  }
  const detail = await expand()
  await act(async () => detail.querySelector<HTMLButtonElement>('button[title="sources/fixture.md"]')!.click())
  expect(state.openWikiDoc).toHaveBeenCalledWith('sources/fixture.md')
  await act(async () => detail.querySelector<HTMLButtonElement>('footer button')!.click())
  expect(state.requestOpenSession).toHaveBeenCalledWith('maintenance-session-id')
})

it('uses readable titles but keeps full paths in tooltips and navigation, including duplicate titles', async () => {
  const paths = ['sources/fixture.md', 'projects/fixture.md']
  state.rows = [task({ result: { changes: paths } })]
  state.wikiPages.mockResolvedValue(paths.map((path) => ({ path, title: '同名知识页' })))
  await render()
  expect(state.wikiPages).not.toHaveBeenCalled()
  const detail = await expand()
  const buttons = [...detail.querySelectorAll<HTMLButtonElement>('section[aria-label="更新页面"] button')]
  expect(buttons).toHaveLength(2)
  for (const [index, button] of buttons.entries()) {
    expect(button.textContent).toBe('同名知识页')
    expect(button.title).toBe(paths[index])
    await act(async () => button.click())
    expect(state.openWikiDoc).toHaveBeenLastCalledWith(paths[index])
  }
  for (const path of paths) expect(detail.textContent).not.toContain(path)
})

it('falls back to file names for missing and blank wiki titles', async () => {
  state.rows = [task({ result: { changes: ['sources/missing.md', 'projects/blank.MD'] } })]
  state.wikiPages.mockResolvedValue([{ path: 'projects/blank.MD', title: '  ' }])
  await render()
  const detail = await expand()
  expect(detail.querySelector('button[title="sources/missing.md"]')?.textContent).toBe('missing')
  expect(detail.querySelector('button[title="projects/blank.MD"]')?.textContent).toBe('blank')
})

it('keeps wiki navigation usable when the page directory request fails', async () => {
  state.wikiPages.mockRejectedValue(new Error('目录暂时不可用'))
  await render()
  const detail = await expand()
  const button = detail.querySelector<HTMLButtonElement>('button[title="sources/fixture.md"]')!
  expect(button.textContent).toBe('fixture')
  await act(async () => button.click())
  expect(state.openWikiDoc).toHaveBeenCalledWith('sources/fixture.md')
  expect(detail.querySelector('footer button')?.textContent).toBe('回到原会话')
})

it('loads new wiki titles when an expanded task finishes and refreshes them on later updates', async () => {
  state.rows = [task({ status: 'planning', result: undefined })]
  await render()
  let detail = await expand()
  expect(state.wikiPages).not.toHaveBeenCalled()
  expect(detail.querySelector('p[aria-label="当前阶段"]')?.textContent).toBe('生成维护计划')

  state.wikiPages.mockResolvedValue([{ path: 'projects/new.md', title: '新生成的页面' }])
  state.rows = [task({ updated_at: '2026-09-23 10:00:02', result: { changes: ['projects/new.md'] } })]
  await render()
  detail = await expand()
  expect(state.wikiPages).toHaveBeenCalledTimes(1)
  expect(detail.querySelector('button[title="projects/new.md"]')?.textContent).toBe('新生成的页面')
  expect(detail.querySelector('p[aria-label="当前阶段"]')).toBeNull()
  expect(toggle().textContent).toContain('成功')

  state.wikiPages.mockResolvedValue([{ path: 'projects/new.md', title: '更新后的页面标题' }])
  state.rows = [task({ updated_at: '2026-09-23 10:00:03', result: { changes: ['projects/new.md'] } })]
  await render()
  expect(state.wikiPages).toHaveBeenCalledTimes(2)
  expect(detail.querySelector('button[title="projects/new.md"]')?.textContent).toBe('更新后的页面标题')
})

it('displays each pending check separately and links its related pages by path', async () => {
  state.rows = [task({ result: { conflicts: [
    { note: '人员名称待核对', between: ['sources/fixture.md', 'projects/missing.md'] },
    { note: '时间范围待核对' },
    { between: ['sources/fixture.md'] },
  ] } })]
  await render()
  const detail = await expand()
  const section = detail.querySelector('section[aria-label="待核对事项"]')!
  const items = [...section.querySelectorAll('li')]
  expect(items).toHaveLength(3)
  expect(section.querySelector('h4')?.textContent).toContain('3')
  expect(items[0].querySelector('p')?.textContent).toBe('人员名称待核对')
  expect(items[0].querySelector('button[title="sources/fixture.md"]')?.textContent).toBe('测试资料')
  const related = items[0].querySelector<HTMLButtonElement>('button[title="projects/missing.md"]')!
  expect(related.textContent).toBe('missing')
  await act(async () => related.click())
  expect(state.openWikiDoc).toHaveBeenCalledWith('projects/missing.md')
  expect(items[1].textContent).toBe('时间范围待核对')
  expect(items[1].querySelector('button')).toBeNull()
  expect(items[2].querySelector('p')?.textContent).toBe('请核对相关页面中的信息。')
  expect(detail.querySelector('section[aria-label="更新页面"]')).toBeNull()
})

it('handles a task without a session, original name, or results without exposing null identifiers', async () => {
  state.rows = [task({ session_id: null, original_name: null, result: undefined })]
  await render()
  const detail = await expand()
  expect(detail.querySelector('header')).toBeNull()
  expect(toggle().getAttribute('aria-label')).toContain('知识库维护')
  expect(detail.textContent).toContain('本次未更新 Wiki 页面。')
  expect(detail.querySelector('footer button')).toBeNull()
  expect(detail.textContent).not.toContain('null')
  expect(state.wikiPages).not.toHaveBeenCalled()
  expect(state.requestOpenSession).not.toHaveBeenCalled()
})

it('keeps details directly below their row, supports collapse, and opens only one task at a time', async () => {
  state.rows = [task(), task({ id: 2, original_name: 'second.pdf' })]
  await render()
  const firstToggle = toggle()
  expect(firstToggle.tagName).toBe('BUTTON')
  expect(firstToggle.getAttribute('aria-expanded')).toBe('false')
  await expand()
  const firstRow = firstToggle.closest('tr')!
  expect(firstRow.nextElementSibling?.querySelector('#task-details-1')).not.toBeNull()
  expect(document.querySelector('#task-details-1')?.getAttribute('data-state')).toBe('open')
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await act(async () => firstToggle.click())
  expect(firstToggle.getAttribute('aria-expanded')).toBe('false')
  expect(document.querySelector('#task-details-1')?.getAttribute('data-state')).toBe('closed')

  await act(async () => firstRow.click())
  expect(firstToggle.getAttribute('aria-expanded')).toBe('true')
  const secondDetail = await expand(2)
  expect(firstToggle.getAttribute('aria-expanded')).toBe('false')
  expect(toggle(2).getAttribute('aria-expanded')).toBe('true')
  expect(secondDetail.closest('[id^="task-details-"]')?.id).toBe('task-details-2')
  expect(document.querySelectorAll('section[aria-label="任务详情"]')).toHaveLength(1)
})

it('shows a prominent failure even when no error message was returned', async () => {
  state.rows = [task({ status: 'failed', error: null, result: undefined })]
  await render()
  const detail = await expand()
  expect(detail.querySelector('header')).toBeNull()
  expect(toggle().textContent).toContain('失败')
  const alert = detail.querySelector('[role="alert"]')!
  expect(alert.className).toContain('text-destructive')
  expect(alert.textContent).toContain('失败原因')
  expect(alert.textContent).toContain('本次维护未完成。')
})

it.each([[390, 2], [820, 4], [1280, 5]])('spans only the visible columns at viewport width %i', async (width, columns) => {
  state.width = width
  await render()
  const detail = await expand()
  expect(detail.closest('td')?.colSpan).toBe(columns)
})

it('keeps timestamps and session action in the footer and shows duration only after completion', async () => {
  state.rows = [task({ status: 'processing' })]
  await render()
  const detail = await expand()
  const footer = detail.querySelector('footer')!
  expect(footer.textContent).toContain('开始')
  expect(footer.textContent).toContain('最近更新')
  expect(footer.textContent).not.toContain('耗时')
  expect(footer.querySelector('[title="2026-09-23 10:00:00"]')).not.toBeNull()
  expect(footer.querySelector('button')?.textContent).toBe('回到原会话')

  state.rows = [task({ updated_at: '2026-09-23 10:00:02' })]
  await render()
  expect(footer.textContent).toContain('结束')
  expect(footer.textContent).toContain('耗时 2s')
  expect(footer.textContent).not.toContain('最近更新')
  expect(footer.querySelector('[title="2026-09-23 10:00:02"]')).not.toBeNull()
})
