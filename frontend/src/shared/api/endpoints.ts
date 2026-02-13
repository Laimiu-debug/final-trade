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
  SignalsResponse,
  SignalScanMode,
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
    timeoutMs: 60_000,
  })
}

export function getScreenerRun(runId: string) {
  return apiRequest<ScreenerRunDetail>(`/api/screener/runs/${runId}`, {
    timeoutMs: 60_000,
  })
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

export function getSignals(params?: {
  mode?: SignalScanMode
  run_id?: string
  refresh?: boolean
  window_days?: number
  min_score?: number
  require_sequence?: boolean
  min_event_count?: number
}) {
  const query = new URLSearchParams()
  if (params?.mode) query.set('mode', params.mode)
  if (params?.run_id) query.set('run_id', params.run_id)
  if (typeof params?.refresh === 'boolean') query.set('refresh', String(params.refresh))
  if (typeof params?.window_days === 'number') query.set('window_days', String(params.window_days))
  if (typeof params?.min_score === 'number') query.set('min_score', String(params.min_score))
  if (typeof params?.require_sequence === 'boolean') {
    query.set('require_sequence', String(params.require_sequence))
  }
  if (typeof params?.min_event_count === 'number') {
    query.set('min_event_count', String(params.min_event_count))
  }
  const suffix = query.toString()
  return apiRequest<SignalsResponse>(`/api/signals${suffix ? `?${suffix}` : ''}`, {
    timeoutMs: 45_000,
  })
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
