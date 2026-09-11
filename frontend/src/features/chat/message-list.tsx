import { useEffect, useRef } from 'react'
import { Markdown } from '@/lib/markdown'
import { useApp } from '@/store/app-state'
import type { ChatMessage } from '@/hooks/use-chat'

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
              {m.pending ? (
                <Thinking />
              ) : (
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
