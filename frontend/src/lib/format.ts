/** 时间显示：2026-08-19 14:30:00 → 08-19 14:30 */
export function fmtTime(s: string | null | undefined): string {
  if (!s) return ''
  const m = String(s).match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/)
  return m ? `${m[1].slice(5)} ${m[2]}` : String(s)
}

export function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}
