import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { ReviewDocument, ReviewFinding, ReviewUnit } from '@/lib/types'
import { cn } from '@/lib/utils'
import { columnName } from './review-state'

interface Props {
  doc: ReviewDocument
  sheet: number
  mode: 'source' | 'ai'
  selected: string[]
  query: string
  disabled: boolean
  findings: ReviewFinding[]
  activeFinding?: string
  onSelect: (ids: string[], additive: boolean) => void
}

/** Plain text only: never interpret uploaded HTML, Markdown, formulas or links. */
export function ReviewDocumentPane({ doc, sheet, mode, selected, query, disabled, onSelect, findings, activeFinding }: Props) {
  const units = doc.sheets.length ? doc.units.filter((u) => u.sheet === sheet) : doc.units
  const expandedRows = new Set(units.filter((u) => selected.includes(u.id)).map((u) => u.row))
  const readable = (value: string) => value.replace(/\[(🔒 [^\]]+)\]\(private:[^)]+\)/g, '$1')
  function content(u: ReviewUnit, value: string, expanded: boolean) {
    if (!expanded) return mode === 'ai' ? readable(value) : value
    // API offsets count Unicode code points (Python), not UTF-16 code units.
    const chars = Array.from(value)
    const matches = findings.filter((f) => u.finding_ids.includes(f.id)).sort((a, b) => a.start - b.start)
    const spans = mode === 'ai' ? u.preview_spans ?? [] : matches.map((f) => ({ finding_id: f.id, start: Math.max(0, f.start - u.start), end: Math.min(chars.length, f.end - u.start) }))
    const result: ReactNode[] = []; let cursor = 0
    for (const span of spans) {
      result.push(mode === 'ai' ? readable(chars.slice(cursor, span.start).join('')) : chars.slice(cursor, span.start).join(''))
      const text = chars.slice(span.start, span.end).join('')
      const active = span.finding_id === activeFinding
      result.push(<mark key={span.finding_id} data-fragment-id={span.finding_id} data-active-fragment={active} className={cn('rounded-sm bg-amber-500/20 text-inherit', active && 'bg-amber-500/40 outline-2 outline-amber-600')}><sup className="mr-1 font-semibold" aria-hidden="true">{matches.findIndex((f) => f.id === span.finding_id) + 1}</sup><span>{mode === 'ai' ? readable(text) : text}</span></mark>)
      cursor = span.end
    }
    result.push(mode === 'ai' ? readable(chars.slice(cursor).join('')) : chars.slice(cursor).join(''))
    return result
  }
  const cell = (u: ReviewUnit) => {
    const expanded = !doc.sheets.length || expandedRows.has(u.row)
    const value = mode === 'source' ? u.text : u.preview
    const protectedValue = u.text !== u.preview
    return <button type="button" disabled={disabled} data-review-unit={u.id} aria-pressed={selected.includes(u.id)}
      onClick={(e) => onSelect([u.id], e.shiftKey)} title={value}
      data-review-row-content={u.row}
      className={cn('block min-h-12 w-full whitespace-pre-wrap break-all px-3 py-2 text-left text-sm transition-colors hover:bg-accent',
        !expanded && 'h-12 overflow-hidden',
        protectedValue && (mode === 'ai' ? 'bg-amber-500/25' : 'bg-amber-500/15'),
        selected.includes(u.id) && 'ring-2 ring-inset ring-ring',
        query && value.toLowerCase().includes(query.toLowerCase()) && 'bg-amber-500/20')}>
      {/* Display a readable label without turning the private reference into a link. */}
      <span className={cn(!expanded && 'line-clamp-2')}>{content(u, value, expanded)}</span>
    </button>
  }
  if (!doc.sheets.length) return <div className="divide-y">{units.map((u) => <div key={u.id} className="flex items-stretch" data-review-row={u.row}><span className="w-10 shrink-0 bg-muted/30 px-2 py-3 text-right font-mono text-xs text-muted-foreground">{u.row}</span><div className="min-w-0 flex-1">{cell(u)}</div></div>)}</div>
  const titles = units.filter((u) => u.row === 0)
  const data = units.filter((u) => u.row !== 0)
  const rows = [...new Set(data.map((u) => u.row!))].sort((a, b) => a - b)
  const cols = [...new Set(data.map((u) => u.col!))].sort((a, b) => a - b)
  const expandedCols = new Set(data.filter((u) => selected.includes(u.id)).map((u) => u.col))
  const columnWidth = (col: number) => expandedCols.has(col) ? 280 : 156
  const lookup = new Map(data.map((u) => [`${u.row}:${u.col}`, u]))
  return <>
    {titles.map((u) => <div className="flex items-center border-b" key={u.id}><Badge variant="outline" className="mx-3 shrink-0">工作表名称</Badge>{cell(u)}</div>)}
    <Table className="table-fixed" style={{ minWidth: Math.max(480, cols.reduce((sum, col) => sum + columnWidth(col), 40)) }}>
      <TableHeader><TableRow><TableHead className="w-10">行</TableHead>{cols.map((col) => <TableHead key={col} style={{ width: columnWidth(col) }}><button disabled={disabled} className="w-full py-2 text-left" aria-label={`选择 ${columnName(col)} 列`} onClick={(e) => onSelect(data.filter((u) => u.col === col && u.text.trim()).map((u) => u.id), e.shiftKey)}>{columnName(col)}</button></TableHead>)}</TableRow></TableHeader>
      <TableBody>{rows.map((row) => <TableRow key={row} data-review-row={row}><TableCell className="bg-muted/30 text-center font-mono text-xs text-muted-foreground">{row}</TableCell>{cols.map((col) => <TableCell key={col} className="border-l p-0 align-top">{lookup.has(`${row}:${col}`) ? cell(lookup.get(`${row}:${col}`)!) : null}</TableCell>)}</TableRow>)}</TableBody>
    </Table>
  </>
}
