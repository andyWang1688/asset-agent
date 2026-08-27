import { describe, expect, it } from 'vitest'
import { settingsModuleFromLocation } from './settings-navigation'

describe('settingsModuleFromLocation', () => {
  it('从设置路由恢复当前模块', () => {
    expect(settingsModuleFromLocation({ pathname: '/settings/retrieval', hash: '' } as Location)).toBe('retrieval')
    expect(settingsModuleFromLocation({ pathname: '/', hash: '#/settings/events' } as Location)).toBe('events')
  })

  it('非法或缺失模块回到模型配置', () => {
    expect(settingsModuleFromLocation({ pathname: '/settings/nope', hash: '' } as Location)).toBe('models')
    expect(settingsModuleFromLocation({ pathname: '/', hash: '' } as Location)).toBe('models')
  })
})
