import { describe, expect, it } from 'vitest'
import { columnName, protectSelection, type ReviewDraft } from './review-state'
import type { ReviewUnit } from '@/lib/types'
const empty: ReviewDraft = { decisions: {}, edits: {}, manual: [] }
function unit(start: number, end: number, ids: string[] = []): ReviewUnit {
  return { id: `document:${start}:${end}`, text: '合成内容', preview: '合成内容', start, end, finding_ids: ids }
}
describe('review selections', () => {
  it('adds every newly selected cell, including a mix of detected and undetected cells', () => {
    const next = protectSelection(empty, [{ source: 'document', unit: unit(0, 4, ['f1']) }, { source: 'document', unit: unit(10, 14) }, { source: 'instruction', unit: unit(0, 4) }], true)
    expect(next.manual).toEqual([{ source: 'document', start: 10, end: 14 }, { source: 'instruction', start: 0, end: 4 }])
    expect(next.decisions).toEqual({ f1: 'store', 'manual:document:10:14': 'store', 'manual:instruction:0:4': 'store' })
    expect(empty.decisions).toEqual({})
    expect(JSON.stringify(next)).not.toContain('合成内容')
  })
  it('cancels and restores a manual mark using its stable finding id', () => {
    const added = protectSelection(empty, [{ source: 'document', unit: unit(0, 4) }], true)
    const selections = [{ source: 'document', unit: unit(0, 4, ['manual:document:0:4']) }]
    const removed = protectSelection(added, selections, false)
    expect(removed.decisions['manual:document:0:4']).toBe('allow')
    expect(protectSelection(removed, selections, true).manual).toHaveLength(1)
  })
  it('keeps the scope limited to the selected finding', () => {
    const next = protectSelection({ ...empty, decisions: { one: 'store', two: 'store' } }, [{ source: 'document', unit: unit(0, 4, ['one']) }], false)
    expect(next.decisions).toEqual({ one: 'allow', two: 'store' })
  })
  it('labels wide worksheets', () => { expect(columnName(27)).toBe('AA') })
})
it('protects missed content in a partially detected line without retaining superseded ids', () => {
  const f = { id: 'partial', source: 'document', start: 1, end: 2, name: '密码', description: '', action: 'store', private_ref: '' }
  const draft = { decisions: { partial: 'store' }, edits: { partial: { name: '旧名' } }, manual: [] }
  const result = protectSelection(draft, [{ source: 'document', unit: unit(0, 4, ['partial']) }], true, [f])
  expect(result.decisions).toEqual({ 'manual:document:0:4': 'store' })
  expect(result.edits).toEqual({})
  expect(result.manual).toEqual([{ source: 'document', start: 0, end: 4 }])
})
