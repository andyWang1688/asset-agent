import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={300}>
      <App />
    </TooltipProvider>
    <Toaster
      position="bottom-center"
      theme="light"
      toastOptions={{
        style: {
          borderRadius: '10px',
          background: 'oklch(22% 0.02 240)',
          color: 'oklch(100% 0 0)',
          border: 'none',
          fontSize: '12.5px',
        },
      }}
    />
  </StrictMode>,
)
