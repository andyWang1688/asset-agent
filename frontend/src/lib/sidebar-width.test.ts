import { describe, expect, it } from 'vitest'
import { SIDEBAR_WIDTH_DEFAULT, SIDEBAR_WIDTH_MAX, SIDEBAR_WIDTH_MIN, clampSidebarWidth, collapseFromDrag, readSidebarWidth } from './sidebar-width'

describe('clampSidebarWidth', () => {
  it('收敛到 min/max', () => {
    expect(clampSidebarWidth(100)).toBe(SIDEBAR_WIDTH_MIN)
    expect(clampSidebarWidth(999)).toBe(SIDEBAR_WIDTH_MAX)
    expect(clampSidebarWidth(236.4)).toBe(236)
  })
})

describe('collapseFromDrag', () => {
  it('展开态拖小过阈值 → 折叠', () => {
    expect(collapseFromDrag(127, false)).toBe(true)
    expect(collapseFromDrag(128, false)).toBe(false)
  })
  it('折叠态拖大过阈值 → 展开', () => {
    expect(collapseFromDrag(127, true)).toBe(true)
    expect(collapseFromDrag(140, true)).toBe(false)
  })
})

describe('readSidebarWidth', () => {
  const store = (v: string | null) => ({ getItem: () => v })
  it('非法/越界回默认', () => {
    expect(readSidebarWidth(store(null))).toBe(SIDEBAR_WIDTH_DEFAULT)
    expect(readSidebarWidth(store('abc'))).toBe(SIDEBAR_WIDTH_DEFAULT)
    expect(readSidebarWidth(store('80'))).toBe(SIDEBAR_WIDTH_DEFAULT)
    expect(readSidebarWidth(store('999'))).toBe(SIDEBAR_WIDTH_DEFAULT)
  })
  it('合法值原样返回', () => {
    expect(readSidebarWidth(store('240'))).toBe(240)
  })
})
