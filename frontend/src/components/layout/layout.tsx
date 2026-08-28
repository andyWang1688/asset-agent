import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { cloneElement, isValidElement, useId, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { fadeTransition, springTransition, stateTransition } from './motion'

const COMPACT_GAP = 'gap-[var(--spacing-compact)]'
const CONTENT_GAP = 'gap-[var(--spacing-content)]'
const CONTENT_PADDING = 'p-[var(--spacing-content)]'

export interface PageShellProps {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  contentClassName?: string
}

export function PageShell({ title, description, actions, children, className, contentClassName }: PageShellProps) {
  return (
    <div className={cn('flex min-h-full flex-col gap-[var(--spacing-section)] p-[var(--spacing-page)] max-[820px]:p-[var(--spacing-page-mobile)] max-[480px]:p-[var(--spacing-page-narrow)]', className)}>
      {(title || description || actions) && (
        <header className={cn('sticky top-0 z-20 -mx-[var(--spacing-page)] -mt-[var(--spacing-page)] flex flex-wrap items-start justify-between bg-surface px-[var(--spacing-page)] pb-[var(--spacing-section)] pt-[var(--spacing-page)] max-[820px]:-mx-[var(--spacing-page-mobile)] max-[820px]:-mt-[var(--spacing-page-mobile)] max-[820px]:px-[var(--spacing-page-mobile)] max-[820px]:pt-[var(--spacing-page-mobile)] max-[480px]:-mx-[var(--spacing-page-narrow)] max-[480px]:-mt-[var(--spacing-page-narrow)] max-[480px]:px-[var(--spacing-page-narrow)] max-[480px]:pt-[var(--spacing-page-narrow)]', CONTENT_GAP)}>
          <div className="min-w-0">
            {title && <h1 className="text-display leading-tight font-bold tracking-[-0.01em]">{title}</h1>}
            {description && <p className="mt-compact text-caption leading-relaxed text-muted">{description}</p>}
          </div>
          {actions && <div className={cn('flex shrink-0 items-center', COMPACT_GAP)}>{actions}</div>}
        </header>
      )}
      <div className={cn('min-h-0 flex-1 overflow-y-auto', contentClassName)}>{children}</div>
    </div>
  )
}

export interface SectionCardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  contentClassName?: string
}

export function SectionCard({ title, description, actions, className, contentClassName, children, ...props }: SectionCardProps) {
  return (
    <section className={cn('motion-card rounded-lg border border-border bg-surface shadow-panel', className)} {...props}>
      {(title || description || actions) && (
        <header className={cn('flex flex-wrap items-start justify-between border-b border-border px-[var(--spacing-content)] py-[var(--spacing-control)]', CONTENT_GAP)}>
          <div className="min-w-0">
            {title && <h2 className="text-panel font-semibold">{title}</h2>}
            {description && <p className="mt-compact text-caption leading-relaxed text-muted">{description}</p>}
          </div>
          {actions && <div className={cn('flex shrink-0 items-center', COMPACT_GAP)}>{actions}</div>}
        </header>
      )}
      <div className={cn(CONTENT_PADDING, contentClassName)}>{children}</div>
    </section>
  )
}

export interface FormRowProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode
  description?: ReactNode
  htmlFor?: string
  error?: ReactNode
  required?: boolean
  control: ReactNode
}

export function FormRow({ label, description, htmlFor, error, required, control, className, ...props }: FormRowProps) {
  const errorId = htmlFor && error ? `${htmlFor}-error` : undefined
  const describedControl = errorId && isValidElement<HTMLAttributes<HTMLElement>>(control)
    ? cloneElement(control, {
        'aria-describedby': [control.props['aria-describedby'], errorId].filter(Boolean).join(' '),
      })
    : control
  return (
    <div className={cn('grid border-b border-border py-[var(--spacing-content)] last:border-b-0 sm:grid-cols-[minmax(150px,0.35fr)_minmax(0,1fr)]', CONTENT_GAP, className)} {...props}>
      <div>
        <label htmlFor={htmlFor} className="text-label font-medium text-fg">
          {label}{required && <span className="ml-[var(--spacing-compact)] text-danger" aria-hidden="true">*</span>}
        </label>
        {description && <p className="mt-compact text-caption leading-relaxed text-muted">{description}</p>}
      </div>
      <div>
        {describedControl}
        {error && <p id={errorId} role="alert" className="mt-compact text-caption text-danger">{error}</p>}
      </div>
    </div>
  )
}

export interface SegmentedControlOption<T extends string> {
  value: T
  label: ReactNode
  disabled?: boolean
}

export interface SegmentedControlProps<T extends string> {
  value: T
  options: readonly SegmentedControlOption<T>[]
  onChange: (value: T) => void
  label?: string
  className?: string
}

export function SegmentedControl<T extends string>({ value, options, onChange, label, className }: SegmentedControlProps<T>) {
  const reduceMotion = useReducedMotion()
  const generatedId = useId()
  const layoutId = label ? `segmented-${label}` : `segmented-${generatedId}`
  return (
    <div className={cn('inline-flex rounded-md border border-border bg-surface p-[var(--spacing-compact)]', className)} role="group" aria-label={label}>
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            disabled={option.disabled}
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className="motion-interactive relative isolate rounded-sm px-[var(--spacing-control)] py-[var(--spacing-compact)] text-caption font-medium text-muted transition-[color,transform] hover:text-fg active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {selected && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 -z-0 rounded-sm bg-fg"
                transition={springTransition(reduceMotion)}
                aria-hidden="true"
              />
            )}
            <span className={cn('relative z-10', selected && 'text-surface')}>{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}

export interface NavHighlightProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  active: boolean
  children: ReactNode
  layoutId?: string
  className?: string
  contentClassName?: string
}

export function NavHighlight({ active, children, layoutId = 'nav-highlight', className, contentClassName, ...props }: NavHighlightProps) {
  const reduceMotion = useReducedMotion()
  return (
    <button type="button" className={cn('motion-interactive relative isolate overflow-hidden transition-[color,transform] active:scale-[0.97]', className)} aria-current={active ? 'page' : undefined} {...props}>
      {active && (
        <motion.span
          layoutId={layoutId}
          className="absolute inset-0 -z-0 rounded-md bg-soft shadow-[inset_2px_0_var(--color-fg)]"
          transition={stateTransition(reduceMotion)}
          aria-hidden="true"
        />
      )}
      <span className={cn('relative z-10', contentClassName)}>{children}</span>
    </button>
  )
}

export interface EmptyStateProps {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div className={cn('flex min-h-40 flex-col items-center justify-center gap-[var(--spacing-compact)] px-[var(--spacing-content)] py-[var(--spacing-section)] text-center', className)} initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={fadeTransition(reduceMotion)}>
      <h2 className="text-heading font-semibold">{title}</h2>
      {description && <p className="max-w-prose text-caption leading-relaxed text-muted">{description}</p>}
      {action && <div className="mt-compact">{action}</div>}
    </motion.div>
  )
}

export interface LoadingStateProps {
  label?: string
  className?: string
}

export function LoadingState({ label = '加载中…', className }: LoadingStateProps) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div className={cn('flex min-h-40 items-center justify-center gap-[var(--spacing-compact)] px-[var(--spacing-content)] py-[var(--spacing-section)] text-caption text-muted', className)} initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={fadeTransition(reduceMotion)} role="status" aria-live="polite">
      <span className="h-[var(--spacing-compact)] w-[var(--spacing-compact)] animate-pulse rounded-pill bg-accent" aria-hidden="true" />
      <span>{label}</span>
    </motion.div>
  )
}

export interface PageTransitionProps {
  children: ReactNode
  pageKey?: string
  className?: string
}

export function PageTransition({ children, pageKey = 'page', className }: PageTransitionProps) {
  const reduceMotion = useReducedMotion()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={pageKey} className={className} initial={reduceMotion ? false : { opacity: 0, y: 'var(--spacing-compact)' }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, y: 'calc(-1 * var(--spacing-compact))' }} transition={fadeTransition(reduceMotion)}>
        {children}
      </motion.div>
    </AnimatePresence>
  )
}
