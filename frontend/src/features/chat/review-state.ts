import type { FindingEdits, ManualMark, ReviewFinding, ReviewUnit } from '@/lib/types'

export interface ReviewDraft {
  edited_text?: string | null
  decisions: Record<string, string>
  edits: FindingEdits
  manual: ManualMark[]
}
export interface ReviewSelection { source: string; unit: ReviewUnit }

/** Coordinates, not client-supplied secrets, are sent back to the local review API. */
export function protectSelection(draft: ReviewDraft, selections: ReviewSelection[], protect: boolean, findings: ReviewFinding[] = []): ReviewDraft {
  const next = { decisions: { ...draft.decisions }, edits: { ...draft.edits }, manual: [...draft.manual] }
  for (const { source, unit } of selections) {
    const partial = unit.finding_ids.length > 0 && unit.finding_ids.every((id) => {
      const f = findings.find((finding) => finding.id === id)
      return f && f.start >= unit.start && f.end <= unit.end && (f.start !== unit.start || f.end !== unit.end)
    })
    if (unit.finding_ids.length && (!protect || !partial)) {
      unit.finding_ids.forEach((id) => { next.decisions[id] = protect ? 'store' : 'allow' })
    } else if (protect && unit.text.trim()) {
      const mark = { source, start: unit.start, end: unit.end }
      const id = `manual:${source}:${unit.start}:${unit.end}`
      // Replacing contained findings must also remove their old decisions/edits.
      unit.finding_ids.forEach((oldId) => { delete next.decisions[oldId]; delete next.edits[oldId] })
      next.manual = next.manual.filter((m) => !(m.source === source && m.start >= mark.start && m.end <= mark.end))
      if (!next.manual.some((m) => m.source === source && m.start === mark.start && m.end === mark.end)) next.manual.push(mark)
      next.decisions[id] = 'store'
    }
  }
  return next
}

export function findingAction(f: ReviewFinding, draft: ReviewDraft) {
  return draft.decisions[f.id] ?? f.action
}

export function columnName(col: number): string {
  let result = ''
  for (let n = col; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + (n - 1) % 26) + result
  return result
}
