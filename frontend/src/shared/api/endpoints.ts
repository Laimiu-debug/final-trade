import { ApiError, apiRequest } from '@/shared/api/client'
import type {
  AIAnalysisRecord,
  AIProviderTestRequest,
  AIProviderTestResponse,
  AppConfig,
  BacktestTaskStartResponse,
  BacktestTaskStatusResponse,
  BacktestResponse,
  BacktestPlateauResponse,
  BacktestPlateauTaskStatusResponse,
  BacktestPlateauRunRequest,
  BacktestRunRequest,
  BoardFilter,
  CandlePoint,
  DeleteAIRecordResponse,
  IntradayPayload,
  MarketNewsResponse,
  MarketDataSyncRequest,
  MarketDataSyncResponse,
  Market,
  PortfolioSnapshot,
  DailyReviewListResponse,
  DailyReviewPayload,
  DailyReviewRecord,
  ReviewResponse,
  ReviewTag,
  ReviewTagCreateRequest,
  ReviewTagStatsResponse,
  ReviewTagsPayload,
  ReviewTagType,
  ScreenerParams,
  ScreenerRunDetail,
  ScreenerRunResponse,
  SignalScanMode,
  SignalsResponse,
  TrendPoolStep,
  SimFillsResponse,
  SimOrdersResponse,
  SimResetResponse,
  SimSettleResponse,
  SimTradeFill,
  SimTradeOrder,
  SimTradingConfig,
  StockAnalysis,
  StockAnnotation,
  SystemStorageStatus,
  TradeFillTagAssignment,
  TradeFillTagUpdateRequest,
  WeeklyReviewListResponse,
  WeeklyReviewPayload,
  WeeklyReviewRecord,
  WyckoffEventStoreBackfillRequest,
  WyckoffEventStoreBackfillResponse,
  WyckoffEventStoreStatsResponse,
} from '@/types/contracts'

export function runScreener(params: ScreenerParams) {
  return apiRequest<ScreenerRunResponse>('/api/screener/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    timeoutMs: 420_000,
  })
}

export function getScreenerRun(runId: string) {
  return apiRequest<ScreenerRunDetail>(`/api/screener/runs/${runId}`, {
    timeoutMs: 60_000,
  })
}

export function getLatestScreenerRun() {
  return apiRequest<ScreenerRunDetail>('/api/screener/latest-run', {
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
  trend_step?: TrendPoolStep
  market_filters?: Market[]
  board_filters?: BoardFilter[]
  as_of_date?: string
  refresh?: boolean
  window_days?: number
  min_score?: number
  require_sequence?: boolean
  min_event_count?: number
}) {
  const query = new URLSearchParams()
  if (params?.mode) query.set('mode', params.mode)
  if (params?.run_id) query.set('run_id', params.run_id)
  if (params?.trend_step) query.set('trend_step', params.trend_step)
  if (params?.market_filters?.length) {
    params.market_filters.forEach((item) => query.append('market_filters', item))
  }
  if (params?.board_filters?.length) {
    params.board_filters.forEach((item) => query.append('board_filters', item))
  }
  if (params?.as_of_date) query.set('as_of_date', params.as_of_date)
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
  const timeoutMs = params?.mode === 'full_market' ? 240_000 : 45_000
  return apiRequest<SignalsResponse>(`/api/signals${suffix ? `?${suffix}` : ''}`, {
    timeoutMs,
  })
}

export function postSimOrder(payload: {
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  signal_date: string
  submit_date: string
}) {
  return apiRequest<{ order: SimTradeOrder; fill?: SimTradeFill }>('/api/sim/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 45_000,
  })
}

export function getPortfolio() {
  return apiRequest<PortfolioSnapshot>('/api/sim/portfolio', {
    timeoutMs: 45_000,
  })
}

export function getSimOrders(params?: {
  status?: 'pending' | 'filled' | 'cancelled' | 'rejected'
  symbol?: string
  side?: 'buy' | 'sell'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}) {
  const query = new URLSearchParams()
  if (params?.status) query.set('status', params.status)
  if (params?.symbol) query.set('symbol', params.symbol)
  if (params?.side) query.set('side', params.side)
  if (params?.date_from) query.set('date_from', params.date_from)
  if (params?.date_to) query.set('date_to', params.date_to)
  if (typeof params?.page === 'number') query.set('page', String(params.page))
  if (typeof params?.page_size === 'number') query.set('page_size', String(params.page_size))
  const suffix = query.toString()
  return apiRequest<SimOrdersResponse>(`/api/sim/orders${suffix ? `?${suffix}` : ''}`, {
    timeoutMs: 45_000,
  })
}

export function getSimFills(params?: {
  symbol?: string
  side?: 'buy' | 'sell'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}) {
  const query = new URLSearchParams()
  if (params?.symbol) query.set('symbol', params.symbol)
  if (params?.side) query.set('side', params.side)
  if (params?.date_from) query.set('date_from', params.date_from)
  if (params?.date_to) query.set('date_to', params.date_to)
  if (typeof params?.page === 'number') query.set('page', String(params.page))
  if (typeof params?.page_size === 'number') query.set('page_size', String(params.page_size))
  const suffix = query.toString()
  return apiRequest<SimFillsResponse>(`/api/sim/fills${suffix ? `?${suffix}` : ''}`, {
    timeoutMs: 45_000,
  })
}

export function cancelSimOrder(orderId: string) {
  return apiRequest<{ order: SimTradeOrder; fill?: SimTradeFill }>(`/api/sim/orders/${orderId}/cancel`, {
    method: 'POST',
    timeoutMs: 45_000,
  })
}

export function settleSim() {
  return apiRequest<SimSettleResponse>('/api/sim/settle', {
    method: 'POST',
    timeoutMs: 60_000,
  })
}

export function resetSim() {
  return apiRequest<SimResetResponse>('/api/sim/reset', {
    method: 'POST',
    timeoutMs: 45_000,
  })
}

export function getSimConfig() {
  return apiRequest<SimTradingConfig>('/api/sim/config')
}

export function updateSimConfig(payload: SimTradingConfig) {
  return apiRequest<SimTradingConfig>('/api/sim/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getReviewStats(params?: {
  date_from?: string
  date_to?: string
  date_axis?: 'sell' | 'buy'
}) {
  const query = new URLSearchParams()
  if (params?.date_from) query.set('date_from', params.date_from)
  if (params?.date_to) query.set('date_to', params.date_to)
  if (params?.date_axis) query.set('date_axis', params.date_axis)
  const suffix = query.toString()
  return apiRequest<ReviewResponse>(`/api/review/stats${suffix ? `?${suffix}` : ''}`, {
    timeoutMs: 45_000,
  })
}

export function runBacktest(payload: BacktestRunRequest) {
  const timeoutMs = payload.mode === 'full_market' ? 240_000 : 60_000
  return apiRequest<BacktestResponse>('/api/backtest/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs,
  })
}

const BACKTEST_PLATEAU_LEGACY_POLL_INTERVAL_MS = 1_500
const BACKTEST_PLATEAU_LEGACY_MAX_WAIT_MS = 12 * 60 * 60 * 1000

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    globalThis.setTimeout(resolve, Math.max(0, Number(ms) || 0))
  })
}

async function waitBacktestPlateauTaskResult(taskId: string): Promise<BacktestPlateauResponse> {
  const deadline = Date.now() + BACKTEST_PLATEAU_LEGACY_MAX_WAIT_MS
  while (true) {
    const status = await getBacktestPlateauTask(taskId)
    if (status.status === 'succeeded') {
      if (status.result) return status.result
      throw new ApiError({
        code: 'BACKTEST_PLATEAU_TASK_EMPTY_RESULT',
        message: '收益平原任务已完成，但未返回结果。',
      })
    }
    if (status.status === 'failed') {
      throw new ApiError({
        code: status.error_code || 'BACKTEST_PLATEAU_TASK_FAILED',
        message: status.error || '收益平原任务失败',
      })
    }
    if (status.status === 'cancelled') {
      throw new ApiError({
        code: 'BACKTEST_PLATEAU_TASK_CANCELLED',
        message: '收益平原任务已停止',
      })
    }
    if (Date.now() >= deadline) {
      throw new ApiError({
        code: 'BACKTEST_PLATEAU_TASK_POLL_TIMEOUT',
        message: '收益平原任务等待超时，请在任务列表继续查看进度。',
      })
    }
    await sleep(BACKTEST_PLATEAU_LEGACY_POLL_INTERVAL_MS)
  }
}

export async function runBacktestPlateau(payload: BacktestPlateauRunRequest) {
  const started = await startBacktestPlateauTask(payload)
  return waitBacktestPlateauTaskResult(started.task_id)
}

export function startBacktestPlateauTask(payload: BacktestPlateauRunRequest) {
  return apiRequest<BacktestTaskStartResponse>('/api/backtest/plateau/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 60_000,
  })
}

export function getBacktestPlateauTask(taskId: string) {
  return apiRequest<BacktestPlateauTaskStatusResponse>(`/api/backtest/plateau/tasks/${taskId}`, {
    timeoutMs: 60_000,
  })
}

export function pauseBacktestPlateauTask(taskId: string) {
  return apiRequest<BacktestPlateauTaskStatusResponse>(`/api/backtest/plateau/tasks/${taskId}/pause`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function resumeBacktestPlateauTask(taskId: string) {
  return apiRequest<BacktestPlateauTaskStatusResponse>(`/api/backtest/plateau/tasks/${taskId}/resume`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function cancelBacktestPlateauTask(taskId: string) {
  return apiRequest<BacktestPlateauTaskStatusResponse>(`/api/backtest/plateau/tasks/${taskId}/cancel`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function startBacktestTask(payload: BacktestRunRequest) {
  return apiRequest<BacktestTaskStartResponse>('/api/backtest/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 60_000,
  })
}

export function getBacktestTask(taskId: string) {
  return apiRequest<BacktestTaskStatusResponse>(`/api/backtest/tasks/${taskId}`, {
    timeoutMs: 60_000,
  })
}

export function pauseBacktestTask(taskId: string) {
  return apiRequest<BacktestTaskStatusResponse>(`/api/backtest/tasks/${taskId}/pause`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function resumeBacktestTask(taskId: string) {
  return apiRequest<BacktestTaskStatusResponse>(`/api/backtest/tasks/${taskId}/resume`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function cancelBacktestTask(taskId: string) {
  return apiRequest<BacktestTaskStatusResponse>(`/api/backtest/tasks/${taskId}/cancel`, {
    method: 'POST',
    timeoutMs: 30_000,
  })
}

export function getDailyReviews(params?: { date_from?: string; date_to?: string }) {
  const query = new URLSearchParams()
  if (params?.date_from) query.set('date_from', params.date_from)
  if (params?.date_to) query.set('date_to', params.date_to)
  const suffix = query.toString()
  return apiRequest<DailyReviewListResponse>(`/api/review/daily${suffix ? `?${suffix}` : ''}`)
}

export function getDailyReview(date: string) {
  return apiRequest<DailyReviewRecord>(`/api/review/daily/${date}`)
}

export function upsertDailyReview(date: string, payload: DailyReviewPayload) {
  return apiRequest<DailyReviewRecord>(`/api/review/daily/${date}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteDailyReview(date: string) {
  return apiRequest<{ deleted: boolean }>(`/api/review/daily/${date}`, {
    method: 'DELETE',
  })
}

export function getWeeklyReviews(params?: { year?: number }) {
  const query = new URLSearchParams()
  if (typeof params?.year === 'number') query.set('year', String(params.year))
  const suffix = query.toString()
  return apiRequest<WeeklyReviewListResponse>(`/api/review/weekly${suffix ? `?${suffix}` : ''}`)
}

export function getWeeklyReview(weekLabel: string) {
  return apiRequest<WeeklyReviewRecord>(`/api/review/weekly/${weekLabel}`)
}

export function upsertWeeklyReview(weekLabel: string, payload: WeeklyReviewPayload) {
  return apiRequest<WeeklyReviewRecord>(`/api/review/weekly/${weekLabel}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteWeeklyReview(weekLabel: string) {
  return apiRequest<{ deleted: boolean }>(`/api/review/weekly/${weekLabel}`, {
    method: 'DELETE',
  })
}

export function getReviewTags() {
  return apiRequest<ReviewTagsPayload>('/api/review/tags')
}

export function createReviewTag(tagType: ReviewTagType, payload: ReviewTagCreateRequest) {
  return apiRequest<ReviewTag>(`/api/review/tags/${tagType}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteReviewTag(tagType: ReviewTagType, tagId: string) {
  return apiRequest<{ deleted: boolean }>(`/api/review/tags/${tagType}/${tagId}`, {
    method: 'DELETE',
  })
}

export function getReviewFillTags() {
  return apiRequest<TradeFillTagAssignment[]>('/api/review/fill-tags')
}

export function getReviewFillTag(orderId: string) {
  return apiRequest<TradeFillTagAssignment>(`/api/review/fill-tags/${orderId}`)
}

export function updateReviewFillTag(orderId: string, payload: TradeFillTagUpdateRequest) {
  return apiRequest<TradeFillTagAssignment>(`/api/review/fill-tags/${orderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getReviewTagStats(params?: { date_from?: string; date_to?: string }) {
  const query = new URLSearchParams()
  if (params?.date_from) query.set('date_from', params.date_from)
  if (params?.date_to) query.set('date_to', params.date_to)
  const suffix = query.toString()
  return apiRequest<ReviewTagStatsResponse>(`/api/review/tag-stats${suffix ? `?${suffix}` : ''}`)
}

export function getMarketNews(params?: {
  query?: string
  symbol?: string
  source_domains?: string[]
  age_hours?: 24 | 48 | 72
  refresh?: boolean
  limit?: number
}) {
  const query = new URLSearchParams()
  if (params?.query) query.set('query', params.query)
  if (params?.symbol) query.set('symbol', params.symbol)
  if (params?.source_domains && params.source_domains.length > 0) {
    query.set('source_domains', params.source_domains.join(','))
  }
  if (typeof params?.age_hours === 'number') query.set('age_hours', String(params.age_hours))
  if (params?.refresh) query.set('refresh', 'true')
  if (typeof params?.limit === 'number') query.set('limit', String(params.limit))
  const suffix = query.toString()
  return apiRequest<MarketNewsResponse>(`/api/market/news${suffix ? `?${suffix}` : ''}`, {
    timeoutMs: 20_000,
  })
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

export function getSystemStorage() {
  return apiRequest<SystemStorageStatus>('/api/system/storage')
}

export function getWyckoffEventStoreStats() {
  return apiRequest<WyckoffEventStoreStatsResponse>('/api/system/wyckoff-event-store/stats')
}

export function backfillWyckoffEventStore(payload: WyckoffEventStoreBackfillRequest) {
  return apiRequest<WyckoffEventStoreBackfillResponse>('/api/system/wyckoff-event-store/backfill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 180_000,
  })
}

export function syncMarketData(payload: MarketDataSyncRequest) {
  return apiRequest<MarketDataSyncResponse>('/api/system/sync-market-data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 180_000,
  })
}
