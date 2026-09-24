import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { api, errMsg } from '@/lib/api'
import { useApp } from '@/store/app-state'
import type { PrivateRefMeta } from '@/lib/types'

/** 私密引用的安全元数据卡：只显示来源/会话/保险柜条目与字段位置，不读取敏感原值。
 *  未登记/未保存引用显示不可用，不编造路径；复制需 clipboard 成功才提示。 */
export function PrivateRefCard() {
  const { privateRefId, closePrivateRef } = useApp()
  const [meta, setMeta] = useState<PrivateRefMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!privateRefId) {
      setMeta(null)
      setError('')
      return
    }
    let cancelled = false
    setLoading(true)
    setMeta(null)
    setError('')
    setCopied(false)
    void api
      .refMetadata(privateRefId)
      .then((m) => {
        if (!cancelled) setMeta(m)
      })
      .catch((e) => {
        if (!cancelled) setError(errMsg(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [privateRefId])

  const open = privateRefId != null

  const lines = meta
    ? [
        `名称：${meta.name || '—'}`,
        `来源：${meta.source || '—'}（${meta.kind || '—'}）`,
        `保险柜类型：${meta.vault_kind || '—'}`,
        `保险柜条目：${meta.vault_name || '—'}`,
        meta.field_name ? `字段：${meta.field_name}` : null,
        meta.item_id ? `条目 ID：${meta.item_id}` : null,
        meta.private_path ? `原件：${meta.private_path}` : null,
        meta.location ? `文件内位置：${meta.location}` : null,
        `报告：#${meta.report_id}`,
      ].filter((l): l is string => !!l)
    : []

  const copy = async () => {
    if (!lines.length) return
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard 失败不提示已复制 */
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) closePrivateRef() }}>
      <SheetContent className="w-[420px] max-w-full sm:w-[420px]">
        <SheetHeader>
          <SheetTitle>私密引用位置</SheetTitle>
          <SheetDescription>这里只显示保险柜和原件位置，不会读取原值。</SheetDescription>
        </SheetHeader>
        {loading ? (
          <div className="flex flex-1 flex-col gap-3 px-5 py-4">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : meta ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
            <dl className="grid gap-1.5 text-[13px] leading-relaxed">
              {[
                ['名称', meta.name || '—'],
                ['来源', `${meta.source || '—'}（${meta.kind || '—'}）`],
                ['保险柜类型', meta.vault_kind || '—'],
                ['保险柜条目', meta.vault_name || '—'],
                ...(meta.field_name ? ([['字段', meta.field_name]] as const) : []),
                ...(meta.item_id ? ([['条目 ID', meta.item_id]] as const) : []),
                ...(meta.private_path ? ([['原件', meta.private_path]] as const) : []),
                ...(meta.location ? ([['文件内位置', meta.location]] as const) : []),
                ['报告', `#${meta.report_id}`],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="w-20 shrink-0 text-muted-foreground">{k}</dt>
                  <dd className="min-w-0 flex-1 break-all">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[11px] text-muted-foreground">请自行到保险柜或本地原件目录查看；这里不提供原文读取。</p>
            <div className="mt-3 flex justify-end">
              <Button variant="outline" size="sm" onClick={() => void copy()}>
                {copied ? '已复制' : '复制位置'}
              </Button>
            </div>
          </div>
        ) : (
          <div className="px-5 py-6 text-center text-[13px] text-muted-foreground">{error || '引用不可用或未保存'}</div>
        )}
      </SheetContent>
    </Sheet>
  )
}
