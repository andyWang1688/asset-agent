import type { Transition } from 'motion/react'

function readToken(name: string) {
  if (typeof window === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function tokenSeconds(name: string) {
  const value = readToken(name)
  if (value.endsWith('ms')) return Number.parseFloat(value) / 1000
  if (value.endsWith('s')) return Number.parseFloat(value)
  return undefined
}

function tokenEase(name: string) {
  const match = readToken(name).match(/^cubic-bezier\(([^)]+)\)$/)
  if (!match) return undefined
  const values = match[1].split(',').map(Number)
  return values.length === 4 && values.every(Number.isFinite)
    ? values as [number, number, number, number]
    : undefined
}

export function springTransition(reduceMotion: boolean | null): Transition {
  if (reduceMotion) return { duration: 0 }
  const visualDuration = tokenSeconds('--motion-duration-standard')
  return visualDuration === undefined ? { type: 'spring' } : { type: 'spring', visualDuration }
}

export function fadeTransition(reduceMotion: boolean | null, index = 0): Transition {
  if (reduceMotion) return { duration: 0 }
  return {
    duration: tokenSeconds('--motion-duration-slow'),
    ease: tokenEase('--motion-ease-fade'),
    delay: (tokenSeconds('--motion-stagger') ?? 0) * index,
  }
}

export function stateTransition(reduceMotion: boolean | null, index = 0): Transition {
  if (reduceMotion) return { duration: 0 }
  return {
    duration: tokenSeconds('--motion-duration-standard'),
    ease: tokenEase('--motion-ease-fade'),
    delay: (tokenSeconds('--motion-stagger') ?? 0) * index,
  }
}

export function staggerTransition(reduceMotion: boolean | null, index = 0): Transition {
  return stateTransition(reduceMotion, index)
}
