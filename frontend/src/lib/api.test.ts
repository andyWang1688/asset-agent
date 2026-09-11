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

describe('问答流', () => {
  it('跨分块解析推理、动作、重试与最终答案事件', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      'event: reasoning\ndata: {"text":"先读"}\n\nevent: reasoning\ndata: {"text":"页面"}\n\nevent: action',
      '\ndata: {"action":"read","path":"projects/a.md"}\n\nevent: retry\ndata: {}\n\nevent: answer\ndata: {"answer":"结果","citations":["projects/a.md"]}\n\n',
    ]
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })))

    const events: string[] = []
    await api.streamQuery('问题', 's-1', {
      onReasoning: (t) => events.push('r:' + t),
      onAction: (a) => events.push('a:' + a.action + ':' + a.path),
      onRetry: () => events.push('retry'),
      onAnswer: (r) => events.push('answer:' + r.answer),
    })
    expect(events).toEqual(['r:先读', 'r:页面', 'a:read:projects/a.md', 'retry', 'answer:结果'])
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
