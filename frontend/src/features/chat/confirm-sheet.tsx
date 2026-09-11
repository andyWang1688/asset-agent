import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ChevronRight, Loader2 } from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { api, errMsg } from '@/lib/api'
import { cn } from '@/lib/utils'
import { fmtTime } from '@/lib/format'
import type { Finding, IngestResult, SubmissionView } from '@/lib/types'

const ACTION_LABELS: Record<string, string> = {
  store: '存入保险柜并脱敏',
  redact: '仅脱敏（销毁原值）',
  allow: '标记误报并放行',
}
const KIND_LABELS: Record<string, string> = {
  credential: '凭证',
  pii: '个人信息',
  unknown_suspect: '疑似',
}
const TYPE_OPTIONS = ['credential', 'pii', 'unknown_suspect']
const VAULT_KINDS = ['login', 'secure_note']

interface Edits {
  type: string
  name: string
  description: string
  vault_kind: string
  vault_name: string
  field_name: string
}

interface ConfirmSheetProps {
  view: SubmissionView | null
  loading: boolean
  onClose: () => void
  onConfirmed: (r: IngestResult) => void
  onCancelled: () => void
}

/** 敏感信息确认闸门：按真实后端字段渲染，支持类型/名称/说明/动作/保险柜条目类型与名称/字段编辑，
 *  以及脱敏预览编辑。程序控制字段（id/span/ref_id/置信度/上下文）只读。 */
export function ConfirmSheet({ view, loading, onClose, onConfirmed, onCancelled }: ConfirmSheetProps) {
  const [preview, setPreview] = useState('')
  const [editingPreview, setEditingPreview] = useState(false)
  const [previewModified, setPreviewModified] = useState(false)
  const [edits, setEdits] = useState<Record<string, Partial<Edits>>>({})
  const [decisions, setDecisions] = useState<Record<string, string>>({})
  const [customizing, setCustomizing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!view) return
    setPreview(view.preview || '')
    setEditingPreview(false)
    setPreviewModified(false)
    setCustomizing(false)
    setError('')
    setSubmitting(false)
    const nextDecisions: Record<string, string> = {}
    for (const f of view.findings) {
      nextDecisions[f.id] = f.suggested_action
    }
    setEdits({})
    setDecisions(nextDecisions)
  }, [view])

  const findings = useMemo(() => view?.findings || [], [view])
  const counts = useMemo(() => view?.summary || {}, [view])
  const total = findings.length

  const patch = useCallback((id: string, part: Partial<Edits>) => {
    setEdits((prev) => ({ ...prev, [id]: { ...prev[id], ...part } }))
    // 改动固定字段会改变占位符/引用：不再以旧预览覆盖，交给后端按最终条目重生成
    setPreviewModified(false)
  }, [])

  const submit = useCallback(async () => {
    if (!view) return
    setSubmitting(true)
    setError('')
    try {
      const r = await api.confirmSubmission(
        view.submission_id,
        decisions,
        view.session_id || '',
        edits,
        previewModified ? preview : undefined,
      )
      toast.success(`已确认，来源 #${r.source_id}，任务 #${r.task_id}`)
      onConfirmed(r)
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSubmitting(false)
    }
  }, [view, decisions, edits, previewModified, preview, onConfirmed])

  const cancel = useCallback(async () => {
    if (!view) return
    try {
      await api.cancelSubmission(view.submission_id)
      toast('已拒绝，密文已销毁。')
      onCancelled()
    } catch (e) {
      setError(errMsg(e))
    }
  }, [view, onCancelled])

  const summary = useMemo(
    () =>
      total === 0
        ? '未检测到敏感内容'
        : `共 ${total} 项 · 凭证 ${counts.credential || 0} · 个人信息 ${counts.pii || 0} · 疑似 ${counts.unknown_suspect || 0}`,
    [total, counts],
  )

  return (
    <Sheet open={!!view} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent
        hideClose
        className="w-[520px] max-w-full sm:w-[520px]"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <SheetHeader>
          <SheetTitle>敏感信息确认</SheetTitle>
          <SheetDescription>
            {view ? `提交 #${view.submission_id}` + (view.original_name ? ` · ${view.original_name}` : '') + (view.created_at ? ` · ${fmtTime(view.created_at)}` : '') : ''}
          </SheetDescription>
        </SheetHeader>

        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted" />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
            <p className={cn('mb-3 text-[13px]', total === 0 ? 'font-semibold text-fg' : 'text-muted')}>{summary}</p>
            <div className="mb-3 flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setCustomizing((o) => !o)}>
                {customizing ? '收起逐项设置' : '按我说的做'}
              </Button>
              <span className="text-caption text-muted">同意将按系统建议一次处理全部发现。</span>
            </div>

            {customizing && (
              <div className="flex flex-col gap-2">
                {findings.map((f) => (
                  <FindingCard key={f.id} f={f} edits={edits[f.id]} decisions={decisions} onPatch={(part) => patch(f.id, part)} onDecision={(a) => setDecisions((p) => ({ ...p, [f.id]: a }))} />
                ))}
              </div>
            )}

            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">{total === 0 ? '资料预览' : '脱敏预览'}</h3>
                {customizing && (
                  <button type="button" className="text-[13px] text-fg hover:underline" onClick={() => setEditingPreview((o) => !o)}>
                    {editingPreview ? '完成修改' : '编辑预览'}
                  </button>
                )}
              </div>
              <Textarea
                aria-label="脱敏预览"
                value={preview}
                readOnly={!editingPreview}
                spellCheck={false}
                onChange={(e) => {
                  setPreview(e.target.value)
                  if (editingPreview) setPreviewModified(true)
                }}
                className={cn('min-h-[150px] font-mono text-caption leading-relaxed', editingPreview ? 'bg-surface' : 'bg-soft opacity-90')}
              />
              {editingPreview && (
                <p className="mt-2 text-caption text-muted">提交时会重新扫描，若仍检测到未处置的敏感信息会被拒绝。</p>
              )}
            </div>

            {error && <p className="mt-control text-label text-danger">{error}</p>}
          </div>
        )}

        <SheetFooter>
          <Button variant="danger" disabled={submitting || loading} onClick={() => setRejectOpen(true)}>
            拒绝
          </Button>
          <Button variant="primary" disabled={submitting || loading} onClick={() => void submit()}>
            {submitting ? '处理中…' : '同意'}
          </Button>
        </SheetFooter>

        <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>拒绝整份资料？</AlertDialogTitle>
              <AlertDialogDescription>整份资料会被丢弃，暂存密文立即销毁；不会调用模型，也不会写入保险柜。</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>返回确认页</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={cancel}>确认拒绝</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </SheetContent>
    </Sheet>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-meta text-muted">{label}</span>
      {children}
    </label>
  )
}

function FindingCard({ f, edits, decisions, onPatch, onDecision }: {
  f: Finding
  edits: Partial<Edits> | undefined
  decisions: Record<string, string>
  onPatch: (part: Partial<Edits>) => void
  onDecision: (a: string) => void
}) {
  const [open, setOpen] = useState(false)
  const e = edits || {}
  const type = e.type ?? f.kind
  const name = e.name ?? f.name ?? ''
  const description = e.description ?? f.description ?? ''
  const vaultKind = e.vault_kind ?? f.vault?.kind ?? 'secure_note'
  const vaultName = e.vault_name ?? f.vault?.name ?? f.name ?? ''
  const fieldName = e.field_name ?? f.vault?.field_name ?? f.name ?? ''
  const action = decisions[f.id] || f.suggested_action
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="motion-card overflow-hidden rounded-lg border border-border bg-surface shadow-panel">
      <CollapsibleTrigger asChild>
        <button type="button" className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-[13px] transition hover:bg-soft">
          <ChevronRight className={cn('motion-interactive h-3 w-3 shrink-0 text-muted transition-transform', open && 'rotate-90')} />
          <Badge variant={f.kind === 'credential' ? 'err' : f.kind === 'pii' ? 'warn' : 'muted'}>{KIND_LABELS[f.kind] || f.kind}</Badge>
          <span className="font-semibold">{f.name || f.rule}</span>
          <span className="ml-auto whitespace-nowrap rounded-pill bg-soft px-2 py-px text-[11px] text-fg">{ACTION_LABELS[action] || action}</span>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-2.5 px-3 pb-3">
        {f.context && <pre className="whitespace-pre-wrap break-all rounded-md bg-soft p-2 font-mono text-caption leading-relaxed text-muted">{f.context}</pre>}
        <Field label="类型">
          <select value={type} onChange={(ev) => onPatch({ type: ev.target.value })} className="rounded-md border border-border bg-bg px-2 py-1.5 text-caption outline-none focus:border-fg/45">
            {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{KIND_LABELS[t] || t}</option>)}
          </select>
        </Field>
        <Field label="可读名称">
          <Input value={name} onChange={(ev) => onPatch({ name: ev.target.value })} />
        </Field>
        <Field label="说明">
          <Input value={description} onChange={(ev) => onPatch({ description: ev.target.value })} />
        </Field>
        <Field label="保存动作">
          <div className="flex flex-col gap-1">
            {(f.allowed_actions || []).map((a) => (
              <label key={a} className="flex cursor-pointer items-center gap-2 text-[13px]">
                <input type="radio" name={`fd-${f.id}`} value={a} checked={action === a} onChange={() => onDecision(a)} className="h-[15px] w-[15px] accent-fg" />
                {ACTION_LABELS[a] || a}
              </label>
            ))}
          </div>
        </Field>
        <Field label="保险柜条目类型">
          <select value={vaultKind} onChange={(ev) => onPatch({ vault_kind: ev.target.value })} className="rounded-md border border-border bg-bg px-2 py-1.5 text-caption outline-none focus:border-fg/45">
            {VAULT_KINDS.map((k) => <option key={k} value={k}>{k === 'login' ? 'Login（账号密码）' : 'Secure Note（字段）'}</option>)}
          </select>
        </Field>
        <Field label="保险柜条目名称">
          <Input value={vaultName} onChange={(ev) => onPatch({ vault_name: ev.target.value })} />
        </Field>
        <Field label="字段名称（Secure Note）">
          <Input value={fieldName} onChange={(ev) => onPatch({ field_name: ev.target.value })} />
        </Field>
        <p className="font-mono text-meta text-muted">引用 {f.ref_id} · 置信度 {Math.round((f.confidence || 0) * 100)}%</p>
      </CollapsibleContent>
    </Collapsible>
  )
}
