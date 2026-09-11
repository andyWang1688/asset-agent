export type Theme = 'light' | 'dark' | 'system'

const KEY = 'assetagent.theme'

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
  } catch {
    return 'system'
  }
}

function systemDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(theme: Theme): void {
  const dark = theme === 'dark' || (theme === 'system' && systemDark())
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* 忽略 */
  }
  applyTheme(theme)
}

/** 跟随系统时响应系统深浅色变化；返回取消函数 */
export function watchSystemTheme(): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (readTheme() === 'system') applyTheme('system')
  }
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}
