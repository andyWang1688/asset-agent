import { useEffect, useState } from 'react'

/** 设计稿流式打字效果：逐字显示 + 尾部光标；prefers-reduced-motion 时直接显示全文 */
export function useTypewriter(text: string, speed: number): { shown: string; typing: boolean } {
  const [shown, setShown] = useState('')
  const [typing, setTyping] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(text)
      setTyping(false)
      return
    }
    setShown('')
    setTyping(true)
    let i = 0
    const timer = window.setInterval(() => {
      i++
      setShown(text.slice(0, i))
      if (i >= text.length) {
        window.clearInterval(timer)
        setTyping(false)
      }
    }, speed)
    return () => window.clearInterval(timer)
  }, [text, speed])

  return { shown, typing }
}
