import { lazy, Suspense } from 'react'
import { AppProvider } from '@/store/app-context'
import { useApp } from '@/store/app-state'
import { AppShell } from '@/components/app-shell'
import { useChat } from '@/hooks/use-chat'
import { LoadingState, PageTransition } from '@/components/layout'

/** 路由级懒加载：四个页面各自成 chunk，首包不再含全部页面代码 */
const ChatPage = lazy(() => import('@/features/chat/chat-page').then((m) => ({ default: m.ChatPage })))
const WikiPage = lazy(() => import('@/features/wiki/wiki-page').then((m) => ({ default: m.WikiPage })))
const TasksPage = lazy(() => import('@/features/tasks/tasks-page').then((m) => ({ default: m.TasksPage })))
const SettingsPage = lazy(() => import('@/features/settings/settings-page').then((m) => ({ default: m.SettingsPage })))

function Shell() {
  const { tab, settingsRoute } = useApp()
  const chat = useChat()
  return (
    <AppShell
      onNavigate={(t) => {
        if (t === 'chat') chat.newChat()
      }}
    >
      {/* 聊天页需要确定高度链（内部滚动）；其余页面按内容自然增高、外层滚动 */}
      <PageTransition pageKey={tab === 'settings' ? `settings-${settingsRoute}` : tab} className={tab === 'chat' ? 'h-full' : 'min-h-full'}>
        <Suspense fallback={<LoadingState label="正在加载页面…" className="min-h-full" />}>
          {tab === 'chat' && <section aria-label="对话" className="h-full"><ChatPage active chat={chat} /></section>}
          {tab === 'wiki' && <section aria-label="知识库"><WikiPage /></section>}
          {tab === 'tasks' && <section aria-label="任务"><TasksPage /></section>}
          {tab === 'settings' && <section aria-label="设置"><SettingsPage /></section>}
        </Suspense>
      </PageTransition>
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
