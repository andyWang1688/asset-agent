import { describe, expect, it } from 'vitest'
import { ApiError } from './api'

describe('ApiError', () => {
  it('携带状态码与消息', () => {
    const e = new ApiError(400, '未配置知识库模型')
    expect(e.status).toBe(400)
    expect(e.message).toBe('未配置知识库模型')
    expect(e).toBeInstanceOf(Error)
  })
})
