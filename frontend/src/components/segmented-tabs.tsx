import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface SegmentedTabsProps<T extends string> {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode }[]
  size?: 'sm' | 'default'
  className?: string
  'aria-label'?: string
}

/**
 * 滑动胶囊分段控件：胶囊位置与宽度按当前选中项测量，切换时平滑滑过去。
 * 宽度不等的标签也不会错位；reduced-motion 下直接切换。
 */
export function SegmentedTabs<T extends string>({
  value,
  onChange,
  options,
  size = 'default',
  className,
  'aria-label': ariaLabel,
}: SegmentedTabsProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [pill, setPill] = useState({ left: 0, width: 0 })

  useLayoutEffect(() => {
    const measure = () => {
      const el = refs.current[value]
      const container = containerRef.current
      if (!el || !container) return
      const r = el.getBoundingClientRect()
      const c = container.getBoundingClientRect()
      setPill({ left: r.left - c.left, width: r.width })
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [value, options])

  return (
    <div
      ref={containerRef}
      role="tablist"
      aria-label={ariaLabel}
      className={cn('relative inline-flex w-fit items-center gap-1 rounded-full bg-muted p-1', className)}
    >
      <span
        aria-hidden="true"
        className="absolute top-1 bottom-1 rounded-full bg-background shadow-sm transition-[left,width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none"
        style={{ left: pill.left, width: pill.width }}
      />
      {options.map((o) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[o.value] = el
          }}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'relative z-10 rounded-full font-medium whitespace-nowrap transition-colors',
            size === 'sm' ? 'px-3 py-1 text-xs' : 'px-3.5 py-1.5 text-[13px]',
            value === o.value ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
