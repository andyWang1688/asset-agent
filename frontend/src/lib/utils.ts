import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [
        'text-meta',
        'text-caption',
        'text-body',
        'text-input',
        'text-panel',
        'text-label',
        'text-heading',
        'text-title',
        'text-display',
      ],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
