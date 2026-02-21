import { AppProviders } from '@/app/providers'
import { AppRoutes } from '@/app/routes'
import { BacktestPlateauTaskWatcher } from '@/shared/components/BacktestPlateauTaskWatcher'
import { BacktestTaskWatcher } from '@/shared/components/BacktestTaskWatcher'

export function App() {
  return (
    <AppProviders>
      <BacktestTaskWatcher />
      <BacktestPlateauTaskWatcher />
      <AppRoutes />
    </AppProviders>
  )
}
