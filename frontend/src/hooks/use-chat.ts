import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errMsg } from '@/lib/api'
import type { SessionMode } from '@/lib/types'

export type TraceItem =
  | { kind: 'reasoning'; text: string }
  | { kind: 'action'; action: string; path?: string; query?: string }

export interface ChatMessage {
  q: string
  a?: string
  cites?: string[]
  semantic?: boolean
  pending?: boolean
  error?: string
  /** 流式思考轨迹：推理原文增量与工具动作按发生顺序排列 */
  trace?: TraceItem[]
  thinkingMs?: number
}

const SESSION_KEY = 'asset-agent.session-id'

function readSessionId(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

function writeSessionId(sid: string | null): void {
  try {
    if (sid) sessionStorage.setItem(SESSION_KEY, sid)
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* 忽略 */
  }
}

/** 会话生命周期：草稿模式选择 → 首次发送创建后端 Session 并锁定模式。
 *  请求代数（generation）用于丢弃过期请求；模式只以后端为准。 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [asking, setAsking] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(readSessionId)
  const [sessionTitle, setSessionTitle] = useState<string | null>(null)
  const [mode, setMode] = useState<SessionMode | null>(null)
  const [draftMode, setDraftMode] = useState<SessionMode>('ask')
  const [hydrating, setHydrating] = useState(() => readSessionId() != null)
  const gen = useRef(0)

  // 刷新/重新打开：只恢复 Session ID，再从后端取真实模式与历史；未知已删除会话回草稿。
  useEffect(() => {
    const sid = readSessionId()
    if (!sid) {
      setHydrating(false)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const sessions = await api.listSessions()
        const s = sessions.find((x) => x.session_id === sid)
        if (cancelled) return
        if (!s) {
          writeSessionId(null)
          setSessionId(null)
          setMode(null)
          setSessionTitle(null)
          setMessages([])
          return
        }
        setSessionId(sid)
        setMode(s.mode)
        setSessionTitle(s.title ?? null)
        if (s.mode === 'ask') {
          const rows = await api.chatHistory()
          if (cancelled) return
          const mine = rows.filter((r) => r.session_id === sid).sort((a, b) => a.id - b.id)
          setMessages(mine.map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })))
        } else {
          setMessages([])
        }
      } catch {
        /* 网络失败：保留草稿，不把空库当已删除 */
        if (!cancelled) { setSessionId(null); setMode(null); setSessionTitle(null); setMessages([]) }
      } finally {
        if (!cancelled) setHydrating(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  /** 确保后端 Session 已按给定模式创建（幂等）；已锁定则校验模式一致。
   *  创建请求返回时校验代数，过期结果不覆盖已打开的新会话。 */
  const ensureSession = useCallback(
    async (m: SessionMode): Promise<{ sessionId: string; mode: SessionMode }> => {
      if (sessionId && mode) {
        if (mode !== m) throw new Error('会话模式已锁定，不能切换')
        return { sessionId, mode }
      }
      const myGen = gen.current
      const created = await api.createSession(m)
      if (myGen !== gen.current) throw new Error('会话已切换')
      setSessionId(created.session_id)
      setMode(created.mode)
      setSessionTitle(created.title ?? null)
      writeSessionId(created.session_id)
      return { sessionId: created.session_id, mode: created.mode }
    },
    [sessionId, mode],
  )

  const ask = useCallback(
    async (question: string) => {
      const myGen = gen.current
      const startedAt = Date.now()
      setAsking(true)
      setMessages((prev) => [...prev, { q: question, pending: true }])

      const appendTrace = (item: TraceItem) => {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (!last || !last.pending) return prev
          const trace = [...(last.trace ?? [])]
          const tail = trace[trace.length - 1]
          if (item.kind === 'reasoning' && tail?.kind === 'reasoning') {
            trace[trace.length - 1] = { kind: 'reasoning', text: tail.text + item.text }
          } else {
            trace.push(item)
          }
          next[next.length - 1] = { ...last, trace }
          return next
        })
      }

      let streamError = ''
      let answered = false
      try {
        const { sessionId: sid } = await ensureSession('ask')
        if (myGen !== gen.current) return null
        await api.streamQuery(question, sid, {
          onReasoning: (text) => {
            if (myGen === gen.current) appendTrace({ kind: 'reasoning', text })
          },
          onAction: (action) => {
            if (myGen === gen.current) appendTrace({ kind: 'action', ...action })
          },
          onRetry: () => {
            if (myGen === gen.current) appendTrace({ kind: 'action', action: 'retry' })
          },
          onAnswer: (r) => {
            answered = true
            if (myGen !== gen.current) return
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (!last || !last.pending) return prev
              next[next.length - 1] = {
                ...last,
                pending: false,
                a: r.answer,
                cites: r.citations || [],
                thinkingMs: Date.now() - startedAt,
              }
              return next
            })
          },
          onError: (message) => {
            streamError = message
          },
        })
        if (myGen !== gen.current) return null // 会话已切换/新建，丢弃过期响应
        if (streamError) {
          setMessages((prev) => prev.slice(0, -1))
          return streamError
        }
        if (!answered) {
          setMessages((prev) => prev.slice(0, -1))
          return '回答中断，请重试'
        }
        return null
      } catch (e) {
        if (myGen !== gen.current) return null
        setMessages((prev) => prev.slice(0, -1))
        return errMsg(e)
      } finally {
        if (myGen === gen.current) setAsking(false)
      }
    },
    [ensureSession],
  )

  /** 从对话历史打开一个已有会话（模式由历史面板传入，但以后端为准，这里仅作恢复） */
  const openSession = useCallback((sid: string, m: SessionMode, msgs: ChatMessage[], title?: string | null) => {
    gen.current += 1
    setAsking(false)
    setSessionId(sid)
    setMode(m)
    setSessionTitle(title ?? null)
    setMessages(msgs)
    writeSessionId(sid)
  }, [])

  /** 从任务详情等入口回到原会话：按 session_id 恢复，模式从后端取回。 */
  const openSessionById = useCallback(async (sid: string) => {
    gen.current += 1
    const myGen = gen.current
    setAsking(false)
    setSessionId(sid)
    setSessionTitle(null)
    setMessages([])
    writeSessionId(sid)
    try {
      const sessions = await api.listSessions()
      const s = sessions.find((x) => x.session_id === sid)
      if (myGen !== gen.current) return
      if (!s) {
        // 会话已删除：回草稿
        setSessionId(null)
        setMode(null)
        writeSessionId(null)
        return
      }
      setMode(s.mode)
      setSessionTitle(s.title ?? null)
      if (s.mode === 'ask') {
        const rows = await api.chatHistory()
        if (myGen !== gen.current) return
        const mine = rows.filter((r) => r.session_id === sid).sort((a, b) => a.id - b.id)
        setMessages(mine.map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })))
      } else {
        setMessages([])
      }
    } catch {
      if (myGen === gen.current) setMode(null) // 恢复失败回草稿，不误清新会话
    }
  }, [])

  /** 新对话：回到草稿选择阶段（只有明确点“新对话”才调用） */
  const newChat = useCallback(() => {
    gen.current += 1
    setAsking(false)
    setSessionId(null)
    setSessionTitle(null)
    setMode(null)
    setMessages([])
    writeSessionId(null)
  }, [])

  return {
    messages,
    asking,
    ask,
    sessionId,
    mode,
    draftMode,
    setDraftMode,
    sessionTitle,
    hydrating,
    openSession,
    openSessionById,
    newChat,
    ensureSession,
  }
}
