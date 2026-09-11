import { useCallback, useEffect, useState } from 'react'
import { BookOpen, Check, ChevronDown, ListTodo, MessageSquare, Monitor, Moon, MoreHorizontal, Plus, Settings, Sun } from 'lucide-react'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import { useSidebar } from '@/components/ui/sidebar'
import { ShouMark, Wordmark } from '@/brand-wordmark'
import { api } from '@/lib/api'
import { fmtTime } from '@/lib/format'
import { readTheme, setTheme, type Theme } from '@/lib/theme'
import type { ChatEntry, SessionInfo } from '@/lib/types'
import { useApp, type Tab } from '@/store/app-state'
import { useTasks } from '@/hooks/use-tasks'
import type { useChat, ChatMessage } from '@/hooks/use-chat'
import { cn } from '@/lib/utils'

const PRIMARY: { tab: Tab; label: string; icon: typeof MessageSquare }[] = [
  { tab: 'chat', label: '对话', icon: MessageSquare },
  { tab: 'wiki', label: '知识库', icon: BookOpen },
  { tab: 'tasks', label: '任务', icon: ListTodo },
  { tab: 'settings', label: '设置', icon: Settings },
]

const THEME_LABEL: Record<Theme, string> = { light: '浅色', dark: '深色', system: '跟随系统' }

function Brand() {
  return (
    <div className="flex items-center px-1">
      <Wordmark className="h-6 w-auto shrink-0 text-foreground group-data-[collapsible=icon]:hidden" />
      <ShouMark className="hidden size-7 shrink-0 text-foreground group-data-[collapsible=icon]:block" />
    </div>
  )
}

interface SessionGroup {
  id: string
  title: string
  time: string
  mode: SessionInfo['mode']
  pinned: boolean
  ids: number[]
  messages: ChatMessage[]
}

function dayLabel(time: string): string {
  const d = new Date(time.replace(' ', 'T'))
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.round((today.getTime() - day.getTime()) / 86400000)
  if (diff <= 0) return '今天'
  if (diff === 1) return '昨天'
  return '更早'
}

/** chat_sessions + chat_log 合并分组：维护会话即使没有问答记录也出现；置顶优先、其余按最近活跃倒序。 */
function groupSessions(sessions: SessionInfo[], rows: ChatEntry[]): SessionGroup[] {
  const map = new Map<string, ChatEntry[]>()
  for (const r of rows) {
    const key = r.session_id || `legacy-${r.id}`
    const list = map.get(key)
    if (list) list.push(r)
    else map.set(key, [r])
  }
  const groups: SessionGroup[] = []
  const seen = new Set<string>()
  for (const s of sessions) {
    const list = map.get(s.session_id) || []
    list.sort((a, b) => a.id - b.id)
    const first = list[0]
    const last = list[list.length - 1] || { created_at: s.created_at }
    const derived = first ? (first.question.length > 22 ? first.question.slice(0, 22) + '…' : first.question) : (s.mode === 'maintain' ? '资料维护' : '对话')
    groups.push({
      id: s.session_id,
      title: s.title || derived,
      time: last.created_at,
      mode: s.mode,
      pinned: s.pinned,
      ids: list.map((r) => r.id),
      messages: list.map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })),
    })
    seen.add(s.session_id)
  }
  for (const [id, list] of map) {
    if (seen.has(id)) continue
    list.sort((a, b) => a.id - b.id)
    const first = list[0]
    const last = list[list.length - 1]
    const derived = first.question.length > 22 ? first.question.slice(0, 22) + '…' : first.question
    groups.push({
      id,
      title: first.title || derived,
      time: last.created_at,
      mode: 'ask',
      pinned: first.pinned,
      ids: list.map((r) => r.id),
      messages: list.map((r) => ({ q: r.question, a: r.answer, cites: r.citations || [] })),
    })
  }
  groups.sort((a, b) => (a.pinned === b.pinned ? (a.time < b.time ? 1 : -1) : a.pinned ? -1 : 1))
  return groups
}

function HistoryNav({ chat }: { chat: ReturnType<typeof useChat> }) {
  const { setTab } = useApp()
  const { sessionId } = chat
  const { isMobile, setOpenMobile } = useSidebar()
  const [groups, setGroups] = useState<SessionGroup[]>([])
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [sessions, chats] = await Promise.all([api.listSessions(), api.chatHistory()])
      setGroups(groupSessions(sessions, chats))
    } catch {
      setGroups([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, sessionId])

  const done = () => {
    if (isMobile) setOpenMobile(false)
  }

  const openSession = (g: SessionGroup) => {
    chat.openSession(g.id, g.mode, g.messages, g.title)
    setTab('chat')
    done()
  }

  const saveRename = async (id: string) => {
    const t = draft.trim()
    setRenaming(null)
    if (!t) return
    try {
      await api.setSessionTitle(id, t)
      await load()
    } catch {
      /* 忽略 */
    }
  }

  const togglePin = async (g: SessionGroup) => {
    try {
      await api.setSessionPin(g.id, !g.pinned)
      await load()
    } catch {
      /* 忽略 */
    }
  }

  const remove = async (id: string) => {
    setDeleting(null)
    try {
      await api.deleteSession(id)
      setGroups((rows) => rows.filter((row) => row.id !== id))
      await load()
    } catch {
      /* 忽略 */
    }
  }

  let lastDay = ''

  return (
    <Collapsible defaultOpen className="group/history">
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel asChild>
          <CollapsibleTrigger className="w-full">
            对话历史
            <ChevronDown className="ml-auto transition-transform duration-200 group-data-[state=closed]/history:-rotate-90" />
          </CollapsibleTrigger>
        </SidebarGroupLabel>
        <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
          <SidebarGroupContent>
            <SidebarMenu>
              {groups.length === 0 && (
                <li className="px-2 py-3 text-xs text-muted-foreground">还没有对话记录</li>
              )}
              {groups.map((g) => {
                const day = g.pinned ? '置顶' : dayLabel(g.time)
                const showDay = day !== lastDay
                lastDay = day
                return (
                  <li key={g.id} className="list-none">
                    {showDay && <div className="px-2 pb-1 pt-3 text-xs text-muted-foreground first:pt-1">{day}</div>}
                    <SidebarMenuItem className="group/session relative">
                      {renaming === g.id ? (
                        <Input
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={() => void saveRename(g.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') void saveRename(g.id)
                            if (e.key === 'Escape') setRenaming(null)
                          }}
                          aria-label="重命名会话"
                          className="my-0.5 h-8 text-xs"
                        />
                      ) : (
                        <SidebarMenuButton isActive={g.id === sessionId} className="h-auto py-1.5 pr-7" onClick={() => openSession(g)}>
                          <div className="flex min-w-0 flex-col items-start gap-0.5">
                            <span className="w-full truncate text-sm">{g.title}</span>
                            <span className="w-full truncate text-xs font-normal text-muted-foreground">
                              {g.mode === 'maintain' ? '维护' : '问答'} · {fmtTime(g.time)}
                            </span>
                          </div>
                        </SidebarMenuButton>
                      )}
                      {renaming !== g.id && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              aria-label="会话操作"
                              className={cn(
                                'absolute right-1 top-1.5 grid size-6 place-items-center rounded-md text-muted-foreground transition-opacity hover:bg-accent hover:text-foreground',
                                'opacity-0 group-hover/session:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100',
                              )}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="size-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="min-w-32">
                            <DropdownMenuItem
                              onSelect={() => {
                                setRenaming(g.id)
                                setDraft(g.title)
                              }}
                            >
                              重命名
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => void togglePin(g)}>{g.pinned ? '取消置顶' : '置顶'}</DropdownMenuItem>
                            <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(g.id)}>
                              删除
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </SidebarMenuItem>
                  </li>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>

      <AlertDialog open={!!deleting} onOpenChange={(o) => { if (!o) setDeleting(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除对话记录？</AlertDialogTitle>
            <AlertDialogDescription>
              只删除这段对话历史，不会删除已入库的资料、原件、保险柜条目或知识库页面。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && void remove(deleting)}>
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Collapsible>
  )
}

function ThemeSwitcher() {
  const [theme, setThemeState] = useState<Theme>(() => readTheme())
  const choose = (t: Theme) => {
    setThemeState(t)
    setTheme(t)
  }
  const Icon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton tooltip={THEME_LABEL[theme]} className="group-data-[collapsible=icon]:mx-auto">
          <Icon />
          <span className="group-data-[collapsible=icon]:hidden">{THEME_LABEL[theme]}</span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-32">
        {(Object.keys(THEME_LABEL) as Theme[]).map((t) => (
          <DropdownMenuItem key={t} onSelect={() => choose(t)}>
            {THEME_LABEL[t]}
            {theme === t && <Check className="ml-auto" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** 应用侧栏：品牌 + 新对话 + 工作区导航 + 对话历史 + 主题；移动端由官方 Sidebar 渲染为抽屉。 */
export function AppSidebar({ chat }: { chat: ReturnType<typeof useChat> }) {
  const { tab, setTab, navigateSettings } = useApp()
  const { attention } = useTasks()
  const { isMobile, setOpenMobile } = useSidebar()

  const go = (t: Tab) => {
    setTab(t)
    if (isMobile) setOpenMobile(false)
  }

  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader>
        <Brand />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  variant="outline"
                  tooltip="新对话"
                  className="justify-center"
                  onClick={() => {
                    chat.newChat()
                    go('chat')
                  }}
                >
                  <Plus />
                  <span>新对话</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>工作区</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {PRIMARY.map((item) => (
                <SidebarMenuItem key={item.tab}>
                  <SidebarMenuButton
                    isActive={tab === item.tab}
                    tooltip={item.label}
                    onClick={() => (item.tab === 'settings' ? navigateSettings('models') : go(item.tab))}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                    {item.tab === 'tasks' && attention.length > 0 && (
                      <Badge variant="secondary" className="ml-auto">
                        {attention.length}
                      </Badge>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <HistoryNav chat={chat} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <ThemeSwitcher />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
