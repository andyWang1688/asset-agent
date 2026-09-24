// @vitest-environment jsdom
import { vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: { models: vi.fn(), presets: vi.fn(), saveModel: vi.fn(), securitySettings: vi.fn(), updateSecuritySettings: vi.fn(), policyRules: vi.fn(), retrievalConfig: vi.fn() },
  app: { refreshHealth: vi.fn(), settingsRoute: 'models', navigateSettings: vi.fn() },
}))

vi.mock('@/lib/api', () => ({ api: mocks.api, errMsg: (e: unknown) => String(e) }))
vi.mock('@/store/app-state', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/store/app-state')>()),
  useApp: () => mocks.app,
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { SettingsPage } from './settings-page'
import { settingsModuleFromLocation, securityTabFromHash, SECURITY_TABS } from './settings-navigation'

let root: Root | null = null

async function render() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  root = createRoot(el)
  await act(async () => {
    root!.render(createElement(SettingsPage))
  })
}

function card(title: string): Element {
  const el = Array.from(document.querySelectorAll('[data-slot="card-title"]')).find((e) => e.textContent === title)
  expect(el, `卡片「${title}」`).toBeTruthy()
  return el!.closest('[data-slot="card"]')!
}

function button(label: string, within: Element | Document = document): HTMLButtonElement {
  const el = Array.from(within.querySelectorAll('button')).find((b) => b.textContent?.trim() === label)
  expect(el, `按钮「${label}」`).toBeTruthy()
  return el as HTMLButtonElement
}

/** 从给定入口打开添加模型 Sheet，填写名称并保存 */
async function addModel(entry: HTMLButtonElement, name: string) {
  await act(async () => entry.click())
  const dialog = document.querySelector('[role=dialog]')
  expect(dialog, '模型 Sheet').toBeTruthy()
  const input = dialog!.querySelector<HTMLInputElement>('#model-name')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, name)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => button('保存', dialog!).click())
}

beforeEach(() => {
  mocks.app.settingsRoute = 'models'
  mocks.app.navigateSettings.mockReset()
  mocks.api.securitySettings.mockReset().mockResolvedValue({ mode: 'default', keywords: { enabled: true, items: [] }, entropy: { enabled: true, sensitivity: 'balanced' } })
  mocks.api.updateSecuritySettings.mockReset().mockResolvedValue({ mode: 'confirm', keywords: { enabled: true, items: [] }, entropy: { enabled: true, sensitivity: 'balanced' } })
  mocks.api.policyRules.mockReset().mockResolvedValue({ rules: [], validators: [] })
  mocks.api.retrievalConfig.mockReset()
  mocks.api.models.mockReset().mockResolvedValue([])
  mocks.api.presets
    .mockReset()
    .mockResolvedValue([{ type: 'custom', name: '自定义', base_url: 'http://localhost:1234/v1', model: 'test-model' }])
  mocks.api.saveModel.mockReset().mockResolvedValue({ id: 1 })
  mocks.app.refreshHealth.mockReset()
})

afterEach(async () => {
  if (root) await act(async () => root!.unmount())
  root = null
  document.body.innerHTML = ''
})

it('安全增强模型卡片顶部入口保存为 security 角色', async () => {
  await render()
  await addModel(button('添加模型', card('安全增强模型')), '安全测试模型')
  expect(mocks.api.saveModel).toHaveBeenCalledTimes(1)
  expect(mocks.api.saveModel.mock.calls[0][0].role).toBe('security')
})

it('安全增强模型空状态入口保存为 security 角色', async () => {
  await render()
  await addModel(button('添加', card('安全增强模型')), '安全测试模型')
  expect(mocks.api.saveModel.mock.calls[0][0].role).toBe('security')
})

it('知识库模型入口仍保存为 knowledge 角色', async () => {
  await render()
  await addModel(button('添加模型', card('知识库模型')), '知识测试模型')
  expect(mocks.api.saveModel.mock.calls[0][0].role).toBe('knowledge')
})

it('设置只保留四个模块，模型统一在模型配置管理', async () => {
  await render()
  expect([...document.querySelectorAll('[role="tab"]')].map((el) => el.textContent)).toEqual(['模型配置', '安全策略', '安全事件', '通用'])
  expect([...document.querySelectorAll('[data-slot="card-title"]')].filter((el) => el.textContent === '安全增强模型')).toHaveLength(1)
  expect(mocks.api.retrievalConfig).not.toHaveBeenCalled()
})

it('安全策略保留检测和处理方式，不再重复管理模型', async () => {
  mocks.app.settingsRoute = 'security'
  await render()
  expect(card('处理方式')).toBeTruthy()
  expect(card('基础检测')).toBeTruthy()
  expect(document.body.textContent).toContain('正则')
  expect(document.body.textContent).not.toContain('安全增强模型')
  expect(document.body.textContent).not.toContain('添加模型')
  expect(document.body.textContent).not.toContain('向量检索')
  const confirm = document.querySelector<HTMLInputElement>('input[name="security-mode"][value="confirm"]')!
  await act(async () => confirm.click())
  expect(mocks.api.updateSecuritySettings).toHaveBeenCalledWith({ mode: 'confirm' })
  expect(mocks.api.retrievalConfig).not.toHaveBeenCalled()
})

it.each([
  ['/settings/retrieval', '', 'models'],
  ['/', '#/settings/retrieval', 'models'],
  ['/settings/security', '#security-model', 'models'],
  ['/settings/security', '#keywords', 'security'],
  ['/settings/rules', '', 'security'],
  ['/settings/about', '', 'general'],
])('旧链接 %s %s 回落到有效设置模块', (pathname, hash, expected) => {
  expect(settingsModuleFromLocation({ pathname, hash })).toBe(expected)
})

it('安全策略标签不再保留模型入口', () => {
  expect(SECURITY_TABS.map((tab) => tab.id)).toEqual(['regex', 'keywords', 'entropy'])
  expect(securityTabFromHash('#security-model')).toBe('regex')
})
