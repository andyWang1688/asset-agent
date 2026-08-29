import * as React from 'react'

/* 上下文与 hook 独立成文件：组件文件保持“只导出组件”，满足 react-refresh 约束。 */
export type SidebarContextProps = {
  state: 'expanded' | 'collapsed'
  open: boolean
  setOpen: (open: boolean) => void
  openMobile: boolean
  setOpenMobile: (open: boolean) => void
  isMobile: boolean
  toggleSidebar: () => void
}

export const SidebarContext = React.createContext<SidebarContextProps | null>(null)

export function useSidebar() {
  const context = React.useContext(SidebarContext)
  if (!context) {
    throw new Error('useSidebar 必须在 SidebarProvider 内使用。')
  }
  return context
}
