import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('ApiError', () => {
  it('携带状态码与消息', () => {
    const e = new ApiError(400, '未配置知识库模型')
    expect(e.status).toBe(400)
    expect(e.message).toBe('未配置知识库模型')
    expect(e).toBeInstanceOf(Error)
  })
})

describe('规则设置 API', () => {
  it('读取统一规则列表并保存内置覆盖', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ rules: [{ name: 'email', source: 'builtin' }], validators: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, rule: { name: 'email', source: 'override' } })))
    vi.stubGlobal('fetch', fetchMock)

    expect((await api.policyRules()).rules[0].source).toBe('builtin')
    expect((await api.setBuiltinOverride('email', { kind: 'credential' })).rule.source).toBe('override')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/settings/policy/builtin-rules/email/override', expect.objectContaining({ method: 'PUT' }))
  })

  it('把覆盖护栏错误返回给页面', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'pattern: 长度不得超过 300' }), { status: 400 })))
    await expect(api.setBuiltinOverride('email', { pattern: 'x'.repeat(301) })).rejects.toThrow('长度不得超过 300')
  })
})
