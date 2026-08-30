/** 侧栏宽度约束（px）：拖拽/键盘调整共用，纯函数便于测试 */
export const SIDEBAR_WIDTH_MIN = 176
export const SIDEBAR_WIDTH_MAX = 320
export const SIDEBAR_WIDTH_DEFAULT = 200
/** 拖拽低于该阈值自动进入 icon-only；高于则恢复展开 */
export const SIDEBAR_ICON_THRESHOLD = 128
export const SIDEBAR_WIDTH_ICON = 64

export function clampSidebarWidth(value: number): number {
  return Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, Math.round(value)))
}

/** 由拖拽目标宽度决定折叠态：跨过阈值才切换，避免抖动 */
export function collapseFromDrag(width: number, collapsed: boolean): boolean {
  if (!collapsed && width < SIDEBAR_ICON_THRESHOLD) return true
  if (collapsed && width >= SIDEBAR_ICON_THRESHOLD) return false
  return collapsed
}

export function readSidebarWidth(storage: Pick<Storage, 'getItem'>): number {
  const raw = Number(storage.getItem('sidebar-width'))
  if (!Number.isFinite(raw) || raw < SIDEBAR_WIDTH_MIN || raw > SIDEBAR_WIDTH_MAX) return SIDEBAR_WIDTH_DEFAULT
  return Math.round(raw)
}
