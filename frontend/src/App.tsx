import { AppProvider, useApp } from '@/store/app-context'
import { AppShell } from '@/components/app-shell'
import { ChatPage } from '@/features/chat/chat-page'
import { WikiPage } from '@/features/wiki/wiki-page'
import { TasksPage } from '@/features/tasks/tasks-page'
import { SettingsPage } from '@/features/settings/settings-page'
import { cn } from '@/lib/utils'

function Shell() {
  const { tab } = useApp()
  return (
    <AppShell>
      <section className={cn('view', tab === 'chat' && 'active')} aria-label="对话">
        <ChatPage active={tab === 'chat'} />
      </section>
      <section className={cn('view', tab === 'wiki' && 'active')} aria-label="知识库">
        <WikiPage />
      </section>
      <section className={cn('view', tab === 'tasks' && 'active')} aria-label="任务">
        <TasksPage />
      </section>
      <section className={cn('view', tab === 'settings' && 'active')} aria-label="设置">
        <SettingsPage />
      </section>
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
