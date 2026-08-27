import { cva } from 'class-variance-authority'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-caption font-medium transition-[background,color,border-color,opacity,transform] duration-150 select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45 active:scale-[0.97] [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-fg text-surface hover:bg-fg/85',
        outline: 'border border-border bg-surface text-fg hover:border-border-strong hover:bg-soft',
        ghost: 'text-muted hover:bg-soft hover:text-fg',
        compact: 'border border-border bg-surface text-fg hover:border-border-strong',
        danger: 'border border-danger/25 bg-danger-soft text-danger hover:bg-danger-soft/70',
        link: 'text-fg underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-8 px-3.5',
        sm: 'h-7 rounded-sm px-2.5 text-meta',
        lg: 'h-9 px-4 text-body',
        icon: 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'outline',
      size: 'default',
    },
  },
)
