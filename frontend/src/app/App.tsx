import { AppProviders } from '@/app/providers'
import { AppRoutes } from '@/app/routes'
import { BacktestTaskWatcher } from '@/shared/components/BacktestTaskWatcher'

export function App() {
  return (
    <AppProviders>
      <BacktestTaskWatcher />
      <AppRoutes />
    </AppProviders>
  )
}
