import { useEffect, useRef } from 'react'
import { ArrowUp, Paperclip, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { cn } from '@/lib/utils'

export type ChatMode = 'ask' | 'maintain'

const PLACEHOLDER: Record<ChatMode, string> = {
  ask: '询问你的资产知识库…',
  maintain: '粘贴要整理的资料，或添加 TXT / Markdown 文件…',
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
  showModeSwitch?: boolean
  onModeChange?: (m: ChatMode) => void
  /** 首页大输入框 */
  large?: boolean
  /** 值变化时聚焦输入框（Cmd/Ctrl+K） */
  focusToken?: number
}

/** 输入区：单层圆角容器；模式切换（仅新对话）在容器内，发送为圆形填充按钮。 */
export function Composer({
  mode,
  value,
  onChange,
  onSend,
  sending,
  sendDisabled,
  fileName,
  onFileChange,
  showModeSwitch = false,
  onModeChange,
  large = false,
  focusToken = 0,
}: ComposerProps) {
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const maintain = mode === 'maintain'

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

  useEffect(() => {
    if (focusToken > 0) taRef.current?.focus()
  }, [focusToken])

  return (
    <div className="rounded-2xl border bg-background p-1.5 shadow-sm transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-4 focus-within:ring-ring/10">
      <Textarea
        ref={taRef}
        value={value}
        spellCheck
        placeholder={PLACEHOLDER[mode]}
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
        className={cn(
          'resize-none border-0 bg-transparent px-3 pt-2.5 leading-relaxed shadow-none focus-visible:ring-0 dark:bg-transparent',
          large ? 'min-h-24 text-lg' : 'min-h-16 text-base',
        )}
      />
      <div className="flex items-center gap-1 px-1 pb-0.5">
        {showModeSwitch ? (
          <SegmentedTabs
            value={mode}
            onChange={(m) => onModeChange?.(m)}
            size="sm"
            aria-label="对话模式"
            options={[
              { value: 'ask', label: '问答' },
              { value: 'maintain', label: '维护' },
            ]}
          />
        ) : (
          <Badge variant="secondary">{maintain ? '维护' : '问答 · 只读'}</Badge>
        )}
        {maintain && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt,.text"
              className="hidden"
              onChange={(e) => {
                onFileChange(e.target.files?.[0] ?? null)
                e.target.value = ''
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="添加附件"
              title="添加附件"
              onClick={() => fileRef.current?.click()}
            >
              <Paperclip />
            </Button>
            {fileName && (
              <span className="inline-flex max-w-48 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
                <span className="truncate">{fileName}</span>
                <button type="button" aria-label="移除附件" onClick={() => onFileChange(null)} className="text-muted-foreground hover:text-foreground">
                  <X className="size-3" />
                </button>
              </span>
            )}
          </>
        )}
        <Button
          type="button"
          size="icon"
          className={cn('ml-auto rounded-full', sending && 'opacity-60')}
          disabled={sendDisabled}
          onClick={onSend}
          aria-label={sending ? '发送中' : '发送'}
          title="发送"
        >
          <ArrowUp />
        </Button>
      </div>
    </div>
  )
}
