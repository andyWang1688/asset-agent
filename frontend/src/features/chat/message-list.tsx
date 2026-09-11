import { useEffect, useRef } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Message, MessageContent } from '@/components/ui/message'
import { fadeTransition } from '@/components/layout'
import { Markdown } from '@/lib/markdown'
import { useApp } from '@/store/app-state'
import type { ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

/** 问答消息流：问题靠右、回答靠左；引用可跳转知识库 */
export function MessageList({ messages, asking }: { messages: ChatMessage[]; asking: boolean }) {
  const { openWikiDoc, openPrivateRef } = useApp()
  const scrollRef = useRef<HTMLDivElement>(null)
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, asking])

  return (
    <div ref={scrollRef} className="flex w-[min(100%,760px)] min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-1 pb-5 pt-1.5">
      <AnimatePresence initial={false}>
      {messages.map((m, i) => (
        <motion.div key={`${i}-${m.q}`} className="flex flex-col gap-2.5" layout>
          <motion.div className="flex w-full" initial={reduceMotion ? false : { opacity: 0, x: 'var(--spacing-content)' }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={fadeTransition(reduceMotion)}>
            <Message align="end">
              <MessageContent>
                <Bubble variant="default" align="end">
                  <BubbleContent>{m.q}</BubbleContent>
                </Bubble>
              </MessageContent>
            </Message>
          </motion.div>
          <motion.div className="flex w-full" initial={reduceMotion ? false : { opacity: 0, x: 'calc(-1 * var(--spacing-content))' }} animate={{ opacity: m.pending ? 0.7 : 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'calc(-1 * var(--spacing-content))' }} transition={fadeTransition(reduceMotion)}>
            <Message>
              <MessageContent>
                <Bubble variant="muted" className={cn(m.pending && 'animate-breathe opacity-70')}>
                  <BubbleContent>{m.pending ? '思考中…' : <Markdown content={m.a ?? ''} onWikiLink={openWikiDoc} onPrivateRef={openPrivateRef} />}</BubbleContent>
                </Bubble>
              </MessageContent>
            </Message>
          </motion.div>
          {m.cites && m.cites.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-meta text-muted">引用</span>
              {m.cites.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => openWikiDoc(c)}
                  className="motion-interactive rounded-sm border border-border bg-surface px-compact py-0.5 font-mono text-meta text-muted transition-colors hover:border-fg hover:text-fg active:scale-[0.97]"
                >
                  {c}
                </button>
              ))}
            </div>
          )}
        </motion.div>
      ))}
      </AnimatePresence>
      {asking && messages.length > 0 && !messages[messages.length - 1].pending && (
        <Message>
          <MessageContent>
            <Bubble variant="muted" className="animate-breathe opacity-70">
              <BubbleContent>思考中…</BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      )}
    </div>
  )
}
