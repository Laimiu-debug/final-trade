import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '@/app/App'
import './index.css'

async function enableMocking() {
  const shouldEnableMocking = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === 'true'
  if (shouldEnableMocking) {
    const { startMockWorker } = await import('@/mocks/browser')
    await startMockWorker()
  }
}

async function bootstrap() {
  await enableMocking()
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void bootstrap()
