import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import App from './App'
import { applyTheme, readTheme, watchSystemTheme } from '@/lib/theme'
import './index.css'

applyTheme(readTheme())
watchSystemTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={300}>
      <App />
    </TooltipProvider>
    <Toaster position="bottom-center" theme="system" />
  </StrictMode>,
)
