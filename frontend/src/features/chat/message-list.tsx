import { useEffect, useRef } from 'react'
import { Markdown } from '@/lib/markdown'
import { useApp } from '@/store/app-context'
import type { ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

/** 问答消息流：问题靠右、回答靠左；引用可跳转知识库 */
export function MessageList({ messages, asking }: { messages: ChatMessage[]; asking: boolean }) {
  const { openWikiDoc } = useApp()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, asking])

  return (
    <div ref={scrollRef} className="flex w-[min(100%,720px)] min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-1 pb-5 pt-1.5">
      {messages.map((m, i) => (
        <div key={i} className="flex flex-col gap-2.5">
          <div className="flex justify-end">
            <div className="max-w-[88%] rounded-md bg-fg px-3.5 py-2 text-caption leading-[1.6] text-surface">{m.q}</div>
          </div>
          <div className="flex justify-start">
            <div className={cn('max-w-[92%] rounded-md bg-soft px-3.5 py-2.5 text-caption leading-[1.6] text-fg', m.pending && 'opacity-70')}>
              {m.pending ? <span>思考中…</span> : <Markdown content={m.a ?? ''} onWikiLink={openWikiDoc} />}
            </div>
          </div>
          {!m.pending && m.semantic === false && (
            <div className="flex justify-start">
              <span className="rounded-sm border border-warn bg-warn-soft px-2 py-0.5 font-mono text-meta text-warn">
                语义召回未启用：本次结果来自关键词匹配
              </span>
            </div>
          )}
          {m.cites && m.cites.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-meta text-muted">引用</span>
              {m.cites.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => openWikiDoc(c)}
                  className="rounded-sm border border-border bg-surface px-2 py-0.5 font-mono text-meta text-muted transition-colors duration-150 hover:border-fg hover:text-fg"
                >
                  {c}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      {asking && messages.length > 0 && !messages[messages.length - 1].pending && (
        <div className="flex justify-start">
          <div className="max-w-[92%] rounded-md bg-soft px-3.5 py-2.5 text-caption text-fg opacity-70">思考中…</div>
        </div>
      )}
    </div>
  )
}
