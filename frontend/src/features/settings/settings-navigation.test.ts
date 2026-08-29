import { describe, expect, it } from 'vitest'
import { securityTabFromHash, settingsModuleFromLocation } from './settings-navigation'

describe('settingsModuleFromLocation', () => {
  it('从设置路由恢复当前模块', () => {
    expect(settingsModuleFromLocation({ pathname: '/settings/retrieval', hash: '' } as Location)).toBe('retrieval')
    expect(settingsModuleFromLocation({ pathname: '/', hash: '#/settings/events' } as Location)).toBe('events')
    expect(settingsModuleFromLocation({ pathname: '/settings/security', hash: '' } as Location)).toBe('security')
    expect(settingsModuleFromLocation({ pathname: '/settings/rules', hash: '' } as Location)).toBe('security')
    expect(settingsModuleFromLocation({ pathname: '/settings/policy', hash: '' } as Location)).toBe('security')
  })

  it('非法或缺失模块回到模型配置', () => {
    expect(settingsModuleFromLocation({ pathname: '/settings/nope', hash: '' } as Location)).toBe('models')
    expect(settingsModuleFromLocation({ pathname: '/', hash: '' } as Location)).toBe('models')
  })
})

describe('securityTabFromHash', () => {
  it('从 hash 恢复二级标签', () => {
    expect(securityTabFromHash('#keywords')).toBe('keywords')
    expect(securityTabFromHash('#security-model')).toBe('security-model')
  })

  it('非法或缺失 hash 回到正则页', () => {
    expect(securityTabFromHash('')).toBe('regex')
    expect(securityTabFromHash('#nope')).toBe('regex')
  })
})
