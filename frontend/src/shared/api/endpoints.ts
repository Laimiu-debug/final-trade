import { apiRequest } from '@/shared/api/client'
import type {
  AIAnalysisRecord,
  AIProviderTestRequest,
  AIProviderTestResponse,
  AppConfig,
  CandlePoint,
  DeleteAIRecordResponse,
  IntradayPayload,
  PortfolioSnapshot,
  ReviewStats,
  ScreenerParams,
  ScreenerRunDetail,
  ScreenerRunResponse,
  SignalResult,
  SimTradeFill,
  SimTradeOrder,
  StockAnalysis,
  StockAnnotation,
  TradeRecord,
} from '@/types/contracts'

export function runScreener(params: ScreenerParams) {
  return apiRequest<ScreenerRunResponse>('/api/screener/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export function getScreenerRun(runId: string) {
  return apiRequest<ScreenerRunDetail>(`/api/screener/runs/${runId}`)
}

export function getStockCandles(symbol: string) {
  return apiRequest<{ symbol: string; candles: CandlePoint[]; degraded: boolean; degraded_reason?: string }>(
    `/api/stocks/${symbol}/candles`,
  )
}

export function getStockIntraday(symbol: string, date: string) {
  const query = new URLSearchParams({ date }).toString()
  return apiRequest<IntradayPayload>(`/api/stocks/${symbol}/intraday?${query}`)
}

export function getStockAnalysis(symbol: string) {
  return apiRequest<{ analysis: StockAnalysis; annotation?: StockAnnotation }>(
    `/api/stocks/${symbol}/analysis`,
  )
}

export function updateStockAnnotation(symbol: string, payload: StockAnnotation) {
  return apiRequest<{ success: true; annotation: StockAnnotation }>(`/api/stocks/${symbol}/annotations`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getSignals() {
  return apiRequest<{ items: SignalResult[] }>('/api/signals')
}

export function postSimOrder(payload: Omit<SimTradeOrder, 'order_id' | 'status'>) {
  return apiRequest<{ order: SimTradeOrder; fill?: SimTradeFill }>('/api/sim/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getPortfolio() {
  return apiRequest<PortfolioSnapshot>('/api/sim/portfolio')
}

export function getReviewStats() {
  return apiRequest<{ stats: ReviewStats; trades: TradeRecord[] }>('/api/review/stats')
}

export function getAIRecords() {
  return apiRequest<{ items: AIAnalysisRecord[] }>('/api/ai/records')
}

export function analyzeStockWithAI(symbol: string) {
  return apiRequest<AIAnalysisRecord>(`/api/stocks/${symbol}/ai-analyze`, {
    method: 'POST',
    timeoutMs: 45_000,
  })
}

export function deleteAIRecord(symbol: string, fetchedAt: string, provider?: string) {
  const params = new URLSearchParams({ symbol, fetched_at: fetchedAt })
  if (provider) {
    params.set('provider', provider)
  }
  return apiRequest<DeleteAIRecordResponse>(`/api/ai/records?${params.toString()}`, {
    method: 'DELETE',
  })
}

export function testAIProvider(payload: AIProviderTestRequest) {
  return apiRequest<AIProviderTestResponse>('/api/ai/providers/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 20_000,
  })
}

export function getConfig() {
  return apiRequest<AppConfig>('/api/config')
}

export function updateConfig(payload: AppConfig) {
  return apiRequest<AppConfig>('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
