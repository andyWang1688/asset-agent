import { lazy, Suspense } from 'react'
import { AppProvider } from '@/store/app-context'
import { useApp } from '@/store/app-state'
import { AppShell } from '@/components/app-shell'
import { useChat } from '@/hooks/use-chat'
import { Skeleton } from '@/components/ui/skeleton'

/** 路由级懒加载：四个页面各自成 chunk，首包不再含全部页面代码 */
const ChatPage = lazy(() => import('@/features/chat/chat-page').then((m) => ({ default: m.ChatPage })))
const WikiPage = lazy(() => import('@/features/wiki/wiki-page').then((m) => ({ default: m.WikiPage })))
const TasksPage = lazy(() => import('@/features/tasks/tasks-page').then((m) => ({ default: m.TasksPage })))
const SettingsPage = lazy(() => import('@/features/settings/settings-page').then((m) => ({ default: m.SettingsPage })))

const TITLES: Record<string, string> = { chat: '对话', wiki: '知识库', tasks: '任务', settings: '设置' }

function Shell() {
  const { tab } = useApp()
  const chat = useChat()
  return (
    <AppShell chat={chat} title={TITLES[tab] ?? ''} pageKey={tab}>
      <Suspense fallback={<Skeleton className="m-6 h-64 flex-1 rounded-xl" />}>
        {tab === 'chat' && <ChatPage chat={chat} />}
        {tab === 'wiki' && <WikiPage />}
        {tab === 'tasks' && <TasksPage />}
        {tab === 'settings' && <SettingsPage />}
      </Suspense>
    </AppShell>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
