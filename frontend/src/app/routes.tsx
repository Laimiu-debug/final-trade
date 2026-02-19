import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/shared/components/AppShell'
import { ScreenerPage } from '@/pages/screener/ScreenerPage'
import { ChartPage } from '@/pages/chart/ChartPage'
import { SignalsPage } from '@/pages/signals/SignalsPage'
import { TradePage } from '@/pages/trade/TradePage'
import { PortfolioPage } from '@/pages/portfolio/PortfolioPage'
import { ReviewPage } from '@/pages/review/ReviewPage'
import { ReviewSharePage } from '@/pages/review/ReviewSharePage'
import { ReviewNewsPage } from '@/pages/review/ReviewNewsPage'
import { AiPage } from '@/pages/ai/AiPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { NotFoundPage } from '@/pages/not-found/NotFoundPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/screener" replace />} />
        <Route path="/screener" element={<ScreenerPage />} />
        <Route path="/stocks/:symbol/chart" element={<ChartPage />} />
        <Route path="/signals" element={<SignalsPage />} />
        <Route path="/trade" element={<TradePage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/review/share" element={<ReviewSharePage />} />
        <Route path="/review/news" element={<ReviewNewsPage />} />
        <Route path="/ai" element={<AiPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
