import { useCallback, useState } from 'react'
import { api } from '@/lib/api'

export interface ChatMessage {
  q: string
  a?: string
  cites?: string[]
  pending?: boolean
  error?: string
}

/** 询问知识：仅承载本次会话的问答；历史记录统一在对话历史面板查看 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [asking, setAsking] = useState(false)

  const ask = useCallback(async (question: string) => {
    setAsking(true)
    setMessages((prev) => [...prev, { q: question, pending: true }])
    try {
      const r = await api.query(question)
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
  }, [])

  return { messages, asking, ask }
}
