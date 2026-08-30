import { useEffect, useRef } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { fadeTransition } from '@/components/layout'
import { Markdown } from '@/lib/markdown'
import { useApp } from '@/store/app-state'
import type { ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

/** 问答消息流：问题靠右、回答靠左；引用可跳转知识库 */
export function MessageList({ messages, asking }: { messages: ChatMessage[]; asking: boolean }) {
  const { openWikiDoc } = useApp()
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
          <div className="flex justify-end">
            <motion.div className="max-w-[88%] rounded-md bg-fg px-3.5 py-2 text-caption leading-[1.6] text-surface" initial={reduceMotion ? false : { opacity: 0, x: 'var(--spacing-content)' }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 'var(--spacing-content)' }} transition={fadeTransition(reduceMotion)}>{m.q}</motion.div>
          </div>
          <div className="flex justify-start">
            <motion.div className={cn('max-w-[92%] rounded-md bg-soft px-3.5 py-2.5 text-caption leading-[1.6] text-fg', m.pending && 'animate-breathe opacity-70')} initial={reduceMotion ? false : { opacity: 0, x: 'calc(-1 * var(--spacing-content))' }} animate={{ opacity: m.pending ? 0.7 : 1, x: 0 }} transition={fadeTransition(reduceMotion)}>
              {m.pending ? <span>思考中…</span> : <Markdown content={m.a ?? ''} onWikiLink={openWikiDoc} />}
            </motion.div>
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
        <div className="flex justify-start">
          <div className="animate-breathe max-w-[92%] rounded-md bg-soft px-3.5 py-2.5 text-caption text-fg opacity-70">思考中…</div>
        </div>
      )}
    </div>
  )
}
