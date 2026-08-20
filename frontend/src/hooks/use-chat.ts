import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { ChatEntry } from '@/lib/types'

export interface ChatMessage {
  q: string
  a?: string
  cites?: string[]
  pending?: boolean
  error?: string
}

/** 询问知识：历史 + 提问（/api/query 与 /api/chat/history） */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [asking, setAsking] = useState(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      const rows: ChatEntry[] = await api.chatHistory()
      if (!mounted.current) return
      setMessages(rows.slice().reverse().map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })))
    } catch {
      /* 历史加载失败不阻塞 */
    }
  }, [])

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

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  return { messages, asking, ask, loadHistory }
}
