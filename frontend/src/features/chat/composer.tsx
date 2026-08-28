import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type ChatMode = 'collect' | 'ask'

const MODE_META: Record<ChatMode, { label: string; placeholder: string }> = {
  collect: { label: '添加资料', placeholder: '粘贴想要整理的资产资料，或描述需要收集的内容…' },
  ask: { label: '添加附件', placeholder: '问问你的资产知识库…' },
}

const MAX_HEIGHT = 180

interface ComposerProps {
  mode: ChatMode
  value: string
  onChange: (v: string) => void
  onSend: () => void
  sending: boolean
  sendDisabled: boolean
  fileName: string | null
  onFileChange: (f: File | null) => void
}

/** 输入区：统一面板边框/圆角/阴影，textarea 无边框，底部附件工具与发送按钮 */
export function Composer({ mode, value, onChange, onSend, sending, sendDisabled, fileName, onFileChange }: ComposerProps) {
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const autoGrow = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, MAX_HEIGHT) + 'px'
    ta.style.overflowY = ta.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }

  useEffect(() => {
    autoGrow()
  }, [value])

  const collect = mode === 'collect'

  return (
    <div className="motion-interactive rounded-lg border border-border bg-surface p-content shadow-pop transition-[border-color,box-shadow] focus-within:border-fg/45 focus-within:ring-[3px] focus-within:ring-soft">
      <textarea
        ref={taRef}
        value={value}
        spellCheck
        placeholder={MODE_META[mode].placeholder}
        aria-label="输入内容"
        onChange={(e) => {
          onChange(e.target.value)
          autoGrow()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            if (!sendDisabled && !sending) onSend()
          }
        }}
        className="w-full resize-none border-0 bg-transparent text-input leading-[1.6] outline-none placeholder:text-muted"
      />
      <div className="mt-1.5 flex items-center justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          {collect && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".md,.txt,.text,.pdf"
                className="hidden"
                onChange={(e) => {
                  onFileChange(e.target.files?.[0] ?? null)
                  e.target.value = ''
                }}
              />
              <button
                type="button"
                aria-label="添加附件"
                onClick={() => fileRef.current?.click()}
                className="motion-interactive inline-flex items-center gap-compact rounded-sm px-compact py-compact text-caption text-muted transition-colors hover:bg-soft hover:text-fg active:scale-[0.97]"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
                  <path d="m20.5 11.5-7.8 7.8a5 5 0 0 1-7.1-7.1l8.5-8.5a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-2.8-2.8l7.7-7.7" />
                </svg>
                {MODE_META[mode].label}
              </button>
              {fileName && (
                <span className="inline-flex max-w-[200px] items-center gap-1.5 rounded-sm bg-soft px-2 py-0.5 text-caption text-fg">
                  <span className="truncate">{fileName}</span>
                  <button type="button" aria-label="移除附件" onClick={() => onFileChange(null)} className="text-fg">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
            </>
          )}
        </div>
        <Button
          type="button"
          variant="primary"
          disabled={sendDisabled}
          onClick={onSend}
          className={cn('h-auto rounded-sm px-[18px] py-2 text-caption font-semibold', sending && 'opacity-60')}
        >
          {sending ? '发送中…' : '发送'}
        </Button>
      </div>
    </div>
  )
}
