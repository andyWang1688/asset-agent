import { useCallback, useState } from 'react'
import { api } from '@/lib/api'

export interface ChatMessage {
  q: string
  a?: string
  cites?: string[]
  pending?: boolean
  error?: string
}

/** 询问知识：承载当前会话（session）的问答；历史记录统一在对话历史面板查看 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [asking, setAsking] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState<string | null>(null)

  const ask = useCallback(
    async (question: string) => {
      setAsking(true)
      const sid = sessionId ?? crypto.randomUUID()
      setSessionId(sid)
      setMessages((prev) => [...prev, { q: question, pending: true }])
      try {
        const r = await api.query(question, sid)
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { q: question, a: r.answer, cites: r.citations || [] }
          return next
        })
        return null
      } catch (e) {
        setMessages((prev) => prev.slice(0, -1))
        return e instanceof Error ? e.message : '提问失败'
      } finally {
        setAsking(false)
      }
    },
    [sessionId],
  )

  /** 从对话历史打开一个已有会话 */
  const openSession = useCallback((sid: string, msgs: ChatMessage[], title?: string | null) => {
    setSessionId(sid)
    setSessionTitle(title ?? null)
    setMessages(msgs)
  }, [])

  /** 新对话：回到空白首页 */
  const newChat = useCallback(() => {
    setSessionId(null)
    setSessionTitle(null)
    setMessages([])
  }, [])

  return { messages, asking, ask, sessionId, sessionTitle, openSession, newChat }
}
