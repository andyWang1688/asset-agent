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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { api, errMsg } from '@/lib/api'
import { cn } from '@/lib/utils'
import { fmtTime } from '@/lib/format'
import type { Finding, IngestResult, SubmissionView } from '@/lib/types'

const ACTION_LABELS: Record<string, string> = {
  store: '存入 Vaultwarden 并脱敏',
  redact: '仅脱敏',
  allow: '标记误报并放行',
}
const ACTION_SHORT: Record<string, string> = {
  store: '存入凭证库',
  redact: '仅脱敏',
  allow: '误报放行',
}
const KIND_BADGE: Record<string, 'err' | 'warn' | 'muted'> = {
  credential: 'err',
  pii: 'warn',
  unknown_suspect: 'muted',
}
const KIND_LABELS: Record<string, string> = {
  credential: '凭证',
  pii: '个人信息',
  unknown_suspect: '疑似',
}

interface ConfirmSheetProps {
  view: SubmissionView | null
  loading: boolean
  onClose: () => void
  onConfirmed: (r: IngestResult) => void
  onCancelled: () => void
}

/** 敏感信息确认闸门：逐项可折叠裁决 + 可编辑脱敏预览；背景点击与 Escape 不关闭 */
export function ConfirmSheet({ view, loading, onClose, onConfirmed, onCancelled }: ConfirmSheetProps) {
  const [preview, setPreview] = useState('')
  const [editing, setEditing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (view) {
      setPreview(view.preview || '')
      setEditing(false)
      setError('')
      setSubmitting(false)
    }
  }, [view])

  const findings = view?.findings || []
  const counts = view?.summary || {}
  const total = findings.length

  const submit = useCallback(async () => {
    if (!view) return
    const decisions: Record<string, string> = {}
    findings.forEach((f) => {
      const el = document.querySelector<HTMLInputElement>(`input[name="fd-${CSS.escape(f.id)}"]:checked`)
      decisions[f.id] = el?.value || f.suggested_action
    })
    setSubmitting(true)
    setError('')
    try {
      const r = await api.confirmSubmission(view.submission_id, decisions, preview)
      toast.success(`已确认，来源 #${r.source_id}，任务 #${r.task_id}`)
      onConfirmed(r)
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setSubmitting(false)
    }
  }, [view, findings, preview, onConfirmed])

  const cancel = useCallback(async () => {
    if (!view) return
    try {
      await api.cancelSubmission(view.submission_id)
      toast('已取消，未产生任何写入。')
      onCancelled()
    } catch (e) {
      setError(errMsg(e))
    }
  }, [view, onCancelled])

  const summary = useMemo(
    () => `共 ${total} 项 · 凭证 ${counts.credential || 0} · 个人信息 ${counts.pii || 0} · 疑似 ${counts.unknown_suspect || 0}`,
    [total, counts],
  )

  return (
    <Sheet open={!!view} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent
        hideClose
        className="w-[480px] max-w-full sm:w-[480px]"
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
            <p className="mb-3 text-xs text-muted">
              请逐项裁决后再继续。确认前：不写入 Vaultwarden、不调用云端编译模型。点击条目展开掩码上下文。
            </p>
            <p className="mb-3 text-[13px] text-muted">{summary}</p>

            <div className="flex flex-col gap-2">
              {findings.map((f) => (
                <FindingCard key={f.id} f={f} />
              ))}
              {findings.length === 0 && <p className="text-xs text-muted">（未发现敏感信息，确认后直接发送）</p>}
            </div>

            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">完整脱敏预览</h3>
                <button
                  type="button"
                  className="text-[13px] text-fg hover:underline"
                  onClick={() => setEditing(!editing)}
                >
                  {editing ? '完成修改' : '修改脱敏'}
                </button>
              </div>
              <Textarea
                value={preview}
                readOnly={!editing}
                spellCheck={false}
                onChange={(e) => setPreview(e.target.value)}
                className={cn(
                  'min-h-[150px] font-mono text-xs leading-relaxed',
                  editing ? 'bg-surface' : 'bg-[#f2f2f5] opacity-90',
                )}
              />
              {editing && (
                <p className="mt-2 text-xs text-muted">
                  可直接编辑脱敏预览；提交时会重新扫描，若仍检测到未处置的敏感信息会被拒绝。
                </p>
              )}
            </div>

            {error && <p className="mt-3 text-[13px] text-[#d70015]">{error}</p>}
          </div>
        )}

        <SheetFooter>
          <Button variant="outline" onClick={() => setCancelOpen(true)}>
            取消
          </Button>
          <Button variant="primary" disabled={submitting || loading} onClick={submit}>
            {submitting ? '处理中…' : '确认并整理'}
          </Button>
        </SheetFooter>

        <AlertDialog open={cancelOpen} onOpenChange={setCancelOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>取消本次提交？</AlertDialogTitle>
              <AlertDialogDescription>
                不会调用云端模型，也不会写入 Vaultwarden；密文将被销毁，可修改后重新提交。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>继续裁决</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={cancel}>
                确认取消
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </SheetContent>
    </Sheet>
  )
}

function FindingCard({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-[13px] transition hover:bg-[#fafafa]"
        >
          <ChevronRight className={cn('h-3 w-3 shrink-0 text-muted transition-transform duration-200', open && 'rotate-90')} />
          <Badge variant={KIND_BADGE[f.kind] || 'info'}>{KIND_LABELS[f.kind] || f.kind}</Badge>
          <span className="font-semibold">{f.rule}</span>
          {f.detector && <span className="text-[11.5px] text-muted">{f.detector}</span>}
          <span className="text-xs text-muted">置信度 {Math.round((f.confidence || 0) * 100)}%</span>
          <span
            className={cn(
              'ml-auto whitespace-nowrap rounded-pill px-2 py-px text-[11px]',
              f.suggested_action === 'store' && 'bg-soft text-fg',
              f.suggested_action === 'redact' && 'bg-[rgba(255,159,10,0.14)] text-[#b25000]',
              f.suggested_action === 'allow' && 'bg-[rgba(52,199,89,0.14)] text-[#1a7f37]',
              !f.suggested_action && 'bg-soft text-muted',
            )}
          >
            建议：{ACTION_SHORT[f.suggested_action] || '—'}
          </span>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3">
        {f.evidence && <p className="mb-2 text-xs text-muted">证据：{f.evidence}</p>}
        <pre className="mb-2 whitespace-pre-wrap break-all rounded-lg bg-[#f2f2f5] p-2.5 font-mono text-xs leading-relaxed text-muted">
          {f.context || ''}
        </pre>
        <div className="flex flex-col gap-0.5">
          {(f.allowed_actions || []).map((a) => (
            <label
              key={a}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition has-[:checked]:bg-soft hover:bg-soft"
            >
              <input
                type="radio"
                name={`fd-${f.id}`}
                value={a}
                defaultChecked={a === f.suggested_action}
                className="h-[15px] w-[15px] shrink-0 accent-fg"
              />
              {ACTION_LABELS[a] || a}
            </label>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
