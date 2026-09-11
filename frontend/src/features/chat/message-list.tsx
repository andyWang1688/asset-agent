import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Markdown } from '@/lib/markdown'
import { cn } from '@/lib/utils'
import { useApp } from '@/store/app-state'
import type { ChatMessage, TraceItem } from '@/hooks/use-chat'

function actionLabel(item: Extract<TraceItem, { kind: 'action' }>): string {
  switch (item.action) {
    case 'index':
      return '读取索引 index.md'
    case 'list':
      return '浏览全部页面'
    case 'read':
      return `读取 ${item.path ?? '页面'}`
    case 'search':
      return `搜索「${item.query ?? ''}」`
    case 'retry':
      return '输出格式异常，正在重试'
    default:
      return item.action || '未知动作'
  }
}

/** 推理原文：限高滚动并跟随最新增量；运行中带流式光标 */
function ReasoningText({ text, live }: { text: string; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [text])
  return (
    <div
      ref={ref}
      className={cn(
        'max-h-44 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground',
        live && 'streaming',
      )}
    >
      {text}
    </div>
  )
}

function TraceList({ items, live = false }: { items: TraceItem[]; live?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5 border-l-2 border-border pl-3">
      {items.map((item, i) =>
        item.kind === 'reasoning' ? (
          <ReasoningText key={i} text={item.text} live={live && i === items.length - 1} />
        ) : (
          <div key={i} className="font-mono text-[11px] text-muted-foreground/80">
            {actionLabel(item)}
          </div>
        ),
      )}
    </div>
  )
}

/** 思考过程：运行中实时流式展示推理与工具动作；完成后收起为一行可展开摘要 */
export function ThoughtBlock({ trace, running, ms }: { trace?: TraceItem[]; running: boolean; ms?: number }) {
  const [open, setOpen] = useState(false)
  const items = trace ?? []

  if (running) {
    return (
      <div className="mb-2 flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>思考中</span>
          <span className="flex gap-1" aria-hidden="true">
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
          </span>
        </div>
        {items.length > 0 && <TraceList items={items} live />}
      </div>
    )
  }

  if (items.length === 0) return null
  const seconds = ms != null ? Math.max(1, Math.round(ms / 1000)) : null

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mb-2">
      <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight className="size-3.5 transition-transform group-data-[state=open]:rotate-90" />
        已深度思考{seconds != null ? ` · ${seconds} 秒` : ''}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="pt-2">
          <TraceList items={items} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 问答消息流：用户浅灰气泡靠右、回答纯文本靠左；引用可跳转知识库。 */
export function MessageList({ messages, asking }: { messages: ChatMessage[]; asking: boolean }) {
  const { openWikiDoc, openPrivateRef } = useApp()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, asking])

  return (
    <div ref={scrollRef} className="flex w-full min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-3">
      <div className="mx-auto flex w-[min(100%,760px)] flex-col gap-4">
        {messages.map((m, i) => (
          <div key={`${i}-${m.q}`} className="flex flex-col gap-3">
            <div className="flex animate-in justify-end fade-in slide-in-from-bottom-1 duration-200 motion-reduce:animate-none">
              <div className="max-w-[80%] rounded-2xl bg-muted px-3.5 py-2 text-sm">{m.q}</div>
            </div>
            <div className="animate-in fade-in slide-in-from-bottom-1 duration-200 motion-reduce:animate-none">
              <ThoughtBlock trace={m.trace} running={!!m.pending} ms={m.thinkingMs} />
              {!m.pending && (
                <div className="max-w-[95%] text-sm leading-relaxed">
                  <Markdown content={m.a ?? ''} onWikiLink={openWikiDoc} onPrivateRef={openPrivateRef} />
                </div>
              )}
            </div>
            {m.cites && m.cites.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] text-muted-foreground">引用</span>
                {m.cites.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => openWikiDoc(c)}
                    className="rounded-md border bg-background px-2 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {asking && messages.length > 0 && !messages[messages.length - 1].pending && <Thinking />}
      </div>
    </div>
  )
}

/** 等待回答：三个跳动点（流式回答由 Markdown 内容增长 + 光标承担） */
export function Thinking() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span>思考中</span>
      <span className="flex gap-1" aria-hidden="true">
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
      </span>
    </div>
  )
}
