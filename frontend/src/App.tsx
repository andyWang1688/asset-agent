import { AppProvider } from '@/store/app-context'
import { useApp } from '@/store/app-state'
import { AppShell } from '@/components/app-shell'
import { ChatPage } from '@/features/chat/chat-page'
import { WikiPage } from '@/features/wiki/wiki-page'
import { TasksPage } from '@/features/tasks/tasks-page'
import { SettingsPage } from '@/features/settings/settings-page'
import { useChat } from '@/hooks/use-chat'
import { PageTransition } from '@/components/layout'

function Shell() {
  const { tab, setTab, settingsRoute } = useApp()
  const chat = useChat()
  return (
    <AppShell
      onOpenSession={(sid, msgs, title) => {
        chat.openSession(sid, msgs, title)
        setTab('chat')
      }}
      onNewChat={() => {
        chat.newChat()
        setTab('chat')
      }}
      onNavigate={(t) => {
        if (t === 'chat') chat.newChat()
      }}
    >
      <PageTransition pageKey={tab === 'settings' ? `settings-${settingsRoute}` : tab} className="min-h-full">
        {tab === 'chat' && <section aria-label="对话"><ChatPage active chat={chat} /></section>}
        {tab === 'wiki' && <section aria-label="知识库"><WikiPage /></section>}
        {tab === 'tasks' && <section aria-label="任务"><TasksPage /></section>}
        {tab === 'settings' && <section aria-label="设置"><SettingsPage /></section>}
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
