import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowLeft, FileText, Table2, LockKeyhole, LockKeyholeOpen, RotateCcw, X } from 'lucide-react'
import { toast } from 'sonner'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, errMsg } from '@/lib/api'
import type { MaintenanceReceipt, ReviewFinding, ReviewUnit, ReviewResponse, SubmissionView } from '@/lib/types'
import { cn } from '@/lib/utils'
import { columnName, findingAction, protectSelection, type ReviewDraft } from './review-state'
import { ReviewDocumentPane } from './review-document-pane'

interface Props {
  view: SubmissionView | null
  loading: boolean
  onClose: () => void
  onConfirmed: (result: MaintenanceReceipt) => void
  onCancelled: () => void
}

/** Keyed child destroys decrypted content and invalidates async work when closed or switched. */
export function ConfirmSheet(props: Props) {
  return props.view ? <ReviewSession key={`${props.view.session_id}:${props.view.submission_id}`} {...props} view={props.view} /> : null
}

function ReviewSession({ view, loading, onClose, onConfirmed, onCancelled }: Props & { view: SubmissionView }) {
  const [draft, setDraft] = useState<ReviewDraft>(() => view.draft ?? ({ decisions: Object.fromEntries(view.findings.map((f) => [f.id, f.suggested_action])), edits: {}, manual: [] }))
  const [review, setReview] = useState<ReviewResponse | null>(null)
  const [checkedDraft, setCheckedDraft] = useState<ReviewDraft | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [editingId, setEditingId] = useState('')
  const [history, setHistory] = useState<ReviewDraft[]>([])
  const [docId, setDocId] = useState('document')
  const [sheet, setSheet] = useState('0')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [reviewError, setReviewError] = useState('')
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState<'confirm' | 'reject' | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const alive = useRef(true)
  const panes = useRef<(HTMLDivElement | null)[]>([])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  // Edits stay local while typing. Only the local review endpoint sees them; never the LLM.
  useEffect(() => {
    if (loading) return
    let active = true
    const timer = setTimeout(() => {
      api.reviewSubmission(view.submission_id, view.session_id || '', draft.decisions, draft.edits, draft.manual).then((result) => {
        if (!active) return
        setReview(result); setCheckedDraft(draft); setReviewError('')
      }).catch((e) => { if (active) setReviewError(errMsg(e)) })
    }, 120)
    return () => { active = false; clearTimeout(timer) }
  }, [draft, loading, reload, view.submission_id, view.session_id])

  const current = checkedDraft === draft && !reviewError && !!review
  const documents = review?.documents ?? []
  const doc = documents.find((d) => d.id === docId) ?? documents[0]
  const navigation = documents.flatMap((d) => d.sheets.length
    ? d.sheets.map((s, index) => ({ key: `${d.id}:${index}`, docId: d.id, sheet: String(index), name: documents.filter((item) => item.id !== 'instruction').length > 1 ? `${d.name} / ${s.name}` : s.name, table: true }))
    : [{ key: `${d.id}:0`, docId: d.id, sheet: '0', name: d.id === 'instruction' ? '附带文字' : d.name === '资料正文' ? view.original_name || '输入文字' : d.name, table: false }])
  const activeName = navigation.find((n) => n.docId === doc?.id && n.sheet === sheet)?.name
  const selections = doc?.units.filter((u) => selected.includes(u.id)).map((unit) => ({ source: doc.id, unit })) ?? []
  const findings = review?.findings ?? []
  const chosen = findings.filter((f) => selections.some(({ unit }) => unit.finding_ids.includes(f.id)))
  const editItems = selections.flatMap<{ id: string; unit: ReviewUnit; finding?: ReviewFinding }>(({ unit }) => {
    const matches = findings.filter((f) => unit.finding_ids.includes(f.id)).sort((a, b) => a.start - b.start)
    return matches.length ? matches.map((finding) => ({ id: `${unit.id}:${finding.id}`, unit, finding })) : [{ id: unit.id, unit, finding: undefined }]
  })
  const editingIndex = Math.max(0, editItems.findIndex((item) => item.id === editingId))
  const editing = editItems[editingIndex]
  const fragment = editing?.finding
  const protectedFragment = fragment && findingAction(fragment, draft) !== 'allow'

  // Observe natural content height, not the shared row height, to avoid resize feedback.
  useLayoutEffect(() => {
    if (typeof ResizeObserver === 'undefined') return
    const contents = panes.current.flatMap((pane) => [...(pane?.querySelectorAll<HTMLElement>('[data-review-row-content]') ?? [])])
    const align = () => {
      const heights = new Map<string, number>()
      for (const content of contents) {
        const key = content.dataset.reviewRowContent!
        heights.set(key, Math.max(heights.get(key) ?? 48, content.getBoundingClientRect().height))
      }
      for (const pane of panes.current) for (const row of pane?.querySelectorAll<HTMLElement>('[data-review-row]') ?? []) {
        row.style.height = `${Math.ceil(heights.get(row.dataset.reviewRow!) ?? 48) + 1}px`
      }
    }
    const observer = new ResizeObserver(align)
    contents.forEach((content) => observer.observe(content)); align()
    return () => observer.disconnect()
  }, [review, selected, doc?.id, sheet])
  useEffect(() => {
    for (const pane of panes.current) {
      const target = pane?.querySelector<HTMLElement>('[data-active-fragment="true"]') ?? pane?.querySelector<HTMLElement>('[data-review-unit][aria-pressed="true"]')
      target?.closest('button')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
      target?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
    }
  }, [editing?.id])
  const invalid = findings.some((f) => findingAction(f, draft) !== 'allow' && !(draft.edits[f.id]?.name ?? f.name).trim())
  const locked = busy !== null
  function change(next: ReviewDraft) {
    if (locked) return
    setHistory((h) => [...h.slice(-29), draft]); setDraft(next); setError(''); setReviewError('')
  }
  function mark(protect: boolean, ids = selected) {
    if (!current || !doc) return
    change(protectSelection(draft, doc.units.filter((u) => ids.includes(u.id)).map((unit) => ({ source: doc.id, unit })), protect, findings))
  }
  function undo() {
    const last = history.at(-1)
    if (!last || locked) return
    setDraft(last); setHistory((h) => h.slice(0, -1)); setReviewError(''); setError('')
  }
  function pick(ids: string[], additive: boolean) {
    setSelected((old) => additive ? [...new Set([...old, ...ids])] : ids)
    setEditingId('')
  }
  function sync(index: number, target: HTMLElement) {
    const other = panes.current[1 - index]
    if (!other || (target !== panes.current[index] && target.dataset.slot !== 'table-container')) return
    const destination = target.dataset.slot === 'table-container' ? other.querySelector<HTMLElement>('[data-slot="table-container"]') : other
    if (destination) {
      if (destination.scrollTop !== target.scrollTop) destination.scrollTop = target.scrollTop
      if (destination.scrollLeft !== target.scrollLeft) destination.scrollLeft = target.scrollLeft
    }
  }
  async function confirm() {
    if (!current || invalid || locked) return
    setBusy('confirm'); setError('')
    try {
      const result = await api.confirmSubmission(view.submission_id, draft.decisions, view.session_id || '', draft.edits, draft.edited_text ?? undefined, draft.manual)
      if (alive.current) { toast.success('维护任务已创建，正在后台处理'); onConfirmed(result) }
    } catch (e) { if (alive.current) { setError(errMsg(e)) } }
    finally { if (alive.current) setBusy(null) }
  }
  async function reject() {
    if (locked) return
    setBusy('reject'); setError('')
    try { await api.cancelSubmission(view.submission_id); if (alive.current) onCancelled() }
    catch (e) { if (alive.current) setError(errMsg(e)) }
    finally { if (alive.current) setBusy(null) }
  }
  return <Sheet open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <SheetContent showCloseButton={false} className="left-1/2 -translate-x-1/2 -translate-y-1/2 gap-0 overflow-hidden rounded-xl border p-0 data-[side=right]:inset-y-auto data-[side=right]:right-auto data-[side=right]:top-1/2 data-[side=right]:h-[min(88svh,880px)] data-[side=right]:w-[94vw] data-[side=right]:sm:max-w-[1440px]" onInteractOutside={(e) => e.preventDefault()}>
      <SheetHeader className="shrink-0 flex-row items-center justify-between border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-3"><Button size="icon-sm" variant="ghost" aria-label="返回对话" disabled={busy !== null} onClick={onClose}><ArrowLeft /></Button><div className="min-w-0"><SheetTitle>资料审查</SheetTitle><SheetDescription className="truncate">{view.original_name || '手动输入'}</SheetDescription></div></div>
        <div className="flex shrink-0 items-center gap-3"><span className="text-xs text-muted-foreground">已保护 {findings.filter((f) => findingAction(f, draft) !== 'allow').length} 处</span><Input className="h-8 w-36" aria-label="查找内容" placeholder="查找内容" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
      </SheetHeader>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="审查目录" className="flex w-36 shrink-0 flex-col gap-1 overflow-y-auto border-r bg-muted/20 p-2 lg:w-44">
          {navigation.map((item) => <Button key={item.key} variant="ghost" size="sm" aria-current={item.docId === doc?.id && item.sheet === sheet ? 'page' : undefined} title={item.name} className="w-full justify-start aria-[current=page]:bg-accent" onClick={() => { setDocId(item.docId); setSheet(item.sheet); setSelected([]) }}>
            {item.table ? <Table2 data-icon="inline-start" /> : <FileText data-icon="inline-start" />}<span className="truncate">{item.name}</span>
          </Button>)}
        </nav>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {!review ? <div role="status" className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">{reviewError ? '审查内容加载失败' : '正在准备资料…'}</div> : <div className="grid min-h-0 flex-1 grid-cols-2 divide-x">
        {(['source', 'ai'] as const).map((mode, index) => <div key={mode} className="flex min-h-0 min-w-0 flex-col">
          <h3 className={cn('flex items-center justify-between border-b px-4 py-2 text-sm font-semibold', mode === 'ai' ? 'bg-amber-500/10' : 'bg-muted/30')}><span>{mode === 'source' ? '本机原文' : '发送给 AI'}</span><Badge variant="outline">{mode === 'source' ? '提取内容 · 只读' : current ? '发送预览' : '正在更新'}</Badge></h3>
          <div key={`${doc?.id}:${sheet}`} ref={(el) => { panes.current[index] = el }} onScrollCapture={(e) => sync(index, e.target as HTMLElement)} className="min-h-0 flex-1 overflow-auto" data-review-pane={mode}>
            {doc && <ReviewDocumentPane doc={doc} sheet={Number(sheet)} mode={mode} query={query} selected={selected} disabled={locked} onSelect={pick} findings={findings} activeFinding={fragment?.id} />}
          </div>
        </div>)}
      </div>}
      {selections.length > 0 && <section className="shrink-0 border-t px-6 py-3" aria-label="所选内容与保存设置">
        <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">{activeName}{selections.length > 1 ? ` · 已选 ${selections.length} 处` : ''}</h3><div className="flex gap-2">{selections.length > 1 && <><Button variant="outline" size="sm" disabled={locked || !current} onClick={() => mark(true)}>保护所选</Button><Button variant="outline" size="sm" disabled={locked || !current || !chosen.some((f) => findingAction(f, draft) !== 'allow')} onClick={() => mark(false)}>取消所选保护</Button></>}<Button variant="ghost" size="icon-sm" aria-label="清除选择" disabled={locked} onClick={() => setSelected([])}><X /></Button></div></div>
        {editing && <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{editing.unit.col ? `${columnName(editing.unit.col)}${editing.unit.row}` : `第 ${editing.unit.row} 行`}</Badge>
            {editItems.length > 1 && <><span className="text-sm text-muted-foreground">片段 {editingIndex + 1} / {editItems.length}</span><Button size="sm" variant="ghost" disabled={locked || editingIndex === 0} onClick={() => setEditingId(editItems[editingIndex - 1].id)}>上一片段</Button><Button size="sm" variant="ghost" disabled={locked || editingIndex === editItems.length - 1} onClick={() => setEditingId(editItems[editingIndex + 1].id)}>下一片段</Button></>}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            {protectedFragment ? <>
              {(['name', 'description'] as const).map((key) => <Field key={key} className="min-w-40 flex-1 gap-2" data-invalid={key === 'name' && !(draft.edits[fragment.id]?.name ?? fragment.name).trim()}>
                <FieldLabel htmlFor={`${fragment.id}-${key}`}>{key === 'name' ? '名称' : '备注（可选）'}</FieldLabel>
                <Input id={`${fragment.id}-${key}`} maxLength={200} disabled={locked} aria-invalid={key === 'name' && !(draft.edits[fragment.id]?.name ?? fragment.name).trim()} value={draft.edits[fragment.id]?.[key] ?? fragment[key]} onChange={(e) => change({ ...draft, edits: { ...draft.edits, [fragment.id]: { ...draft.edits[fragment.id], [key]: e.target.value } } })} />
              </Field>)}
              <Button variant="outline" disabled={locked || !current} className="border-destructive/40 text-destructive hover:text-destructive" onClick={() => change({ ...draft, decisions: { ...draft.decisions, [fragment.id]: 'allow' } })}><LockKeyholeOpen data-icon="inline-start" />取消保护</Button>
            </> : <><span className="mb-2 flex-1 text-sm text-muted-foreground">未保护 · 将明文发送</span><Button variant="outline" disabled={locked || !current || !editing.unit.text.trim()} onClick={() => fragment ? change({ ...draft, decisions: { ...draft.decisions, [fragment.id]: 'store' } }) : mark(true, [editing.unit.id])}><LockKeyhole data-icon="inline-start" />{fragment ? '恢复保护' : '保护内容'}</Button></>}
            {protectedFragment && fragment.start >= editing.unit.start && fragment.end <= editing.unit.end && (fragment.start !== editing.unit.start || fragment.end !== editing.unit.end) && <Button variant="outline" disabled={locked || !current} onClick={() => mark(true, [editing.unit.id])}>{editing.unit.col ? '保护整个单元格' : '保护整行'}</Button>}
          </div>
        </div>}

      </section>}
        </div>
      </div>
      {(error || reviewError || invalid) && <div role="alert" className="px-6 py-2 text-sm text-destructive">{invalid ? '名称不能为空，请补全后继续。' : reviewError || error}{reviewError && <Button variant="link" size="sm" onClick={() => setReload((n) => n + 1)}>重新加载</Button>}</div>}
      <SheetFooter className="mt-0 shrink-0 flex-row items-center justify-between border-t px-6 py-3"><div>{history.length > 0 && <Button size="sm" variant="outline" disabled={locked} onClick={undo}><RotateCcw data-icon="inline-start" />撤销</Button>}</div><div className="flex gap-2">
        <Button variant="ghost" className="text-destructive" disabled={locked} onClick={() => setRejectOpen(true)}>拒绝导入</Button>
        <Button className="bg-emerald-600 text-white hover:bg-emerald-700" disabled={locked || !current || invalid} onClick={() => void confirm()}>{busy === 'confirm' ? '正在提交…' : '确认并开始维护'}</Button>
      </div></SheetFooter>
      <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>拒绝整份资料？</AlertDialogTitle><AlertDialogDescription>暂存密文将被销毁，不执行维护计划。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>返回审查</AlertDialogCancel><AlertDialogAction variant="destructive" onClick={() => void reject()}>确定拒绝</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </SheetContent>
  </Sheet>
}
