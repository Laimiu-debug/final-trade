import { delay, http, HttpResponse } from 'msw'
import {
  analyzeStockWithAI,
  cancelOrder,
  createOrder,
  createScreenerRun,
  deleteAIRecord,
  getFills,
  getAIRecords,
  getAnalysis,
  getCandlePayload,
  getIntradayPayload,
  getConfigStore,
  getOrders,
  getPortfolio,
  getReview,
  getSimConfigStore,
  getScreenerRun,
  getSignals,
  getSystemStorageStore,
  resetAccount,
  saveAnnotation,
  setSimConfigStore,
  syncMarketDataStore,
  settleOrders,
  setConfigStore,
  testAIProvider,
} from '@/mocks/data'
import type {
  AIProviderTestRequest,
  AppConfig,
  MarketDataSyncRequest,
  ScreenerParams,
  StockAnnotation,
} from '@/types/contracts'

export const handlers = [
  http.post('/api/screener/run', async ({ request }) => {
    const params = (await request.json()) as ScreenerParams
    await delay(420)
    const detail = createScreenerRun(params)
    return HttpResponse.json({ run_id: detail.run_id })
  }),

  http.get('/api/screener/runs/:runId', async ({ params }) => {
    await delay(260)
    const run = getScreenerRun(String(params.runId))
    if (!run) {
      return HttpResponse.json(
        {
          code: 'RUN_NOT_FOUND',
          message: '筛选任务不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    return HttpResponse.json(run)
  }),

  http.get('/api/stocks/:symbol/candles', async ({ params }) => {
    await delay(180)
    return HttpResponse.json(getCandlePayload(String(params.symbol)))
  }),

  http.get('/api/stocks/:symbol/intraday', async ({ params, request }) => {
    await delay(150)
    const date = new URL(request.url).searchParams.get('date') ?? ''
    return HttpResponse.json(getIntradayPayload(String(params.symbol), date))
  }),

  http.get('/api/stocks/:symbol/analysis', async ({ params }) => {
    await delay(160)
    return HttpResponse.json(getAnalysis(String(params.symbol)))
  }),

  http.post('/api/stocks/:symbol/ai-analyze', async ({ params }) => {
    await delay(420)
    return HttpResponse.json(analyzeStockWithAI(String(params.symbol)))
  }),

  http.put('/api/stocks/:symbol/annotations', async ({ request, params }) => {
    const body = (await request.json()) as StockAnnotation
    if (body.symbol !== params.symbol) {
      return HttpResponse.json(
        {
          code: 'SYMBOL_MISMATCH',
          message: 'symbol 与 URL 不一致',
          trace_id: `${Date.now()}`,
        },
        { status: 400 },
      )
    }
    const saved = saveAnnotation(body)
    return HttpResponse.json({
      success: true,
      annotation: saved,
    })
  }),

  http.get('/api/signals', async ({ request }) => {
    await delay(120)
    const url = new URL(request.url)
    const mode = (url.searchParams.get('mode') ?? 'trend_pool') as 'trend_pool' | 'full_market'
    const refresh = url.searchParams.get('refresh') === 'true'
    const windowDays = Number(url.searchParams.get('window_days') ?? 60)
    const minScore = Number(url.searchParams.get('min_score') ?? 60)
    const requireSequence = url.searchParams.get('require_sequence') === 'true'
    const minEventCount = Number(url.searchParams.get('min_event_count') ?? 1)
    return HttpResponse.json(
      getSignals({
        mode,
        window_days: Number.isFinite(windowDays) ? windowDays : 60,
        min_score: Number.isFinite(minScore) ? minScore : 60,
        require_sequence: requireSequence,
        min_event_count: Number.isFinite(minEventCount) ? minEventCount : 1,
      }),
      {
        headers: {
          'x-mock-refresh': String(refresh),
        },
      },
    )
  }),

  http.post('/api/sim/orders', async ({ request }) => {
    await delay(160)
    const payload = (await request.json()) as {
      symbol: string
      side: 'buy' | 'sell'
      quantity: number
      signal_date: string
      submit_date: string
    }
    return HttpResponse.json(createOrder(payload))
  }),

  http.get('/api/sim/orders', async ({ request }) => {
    await delay(120)
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? 1)
    const pageSize = Number(url.searchParams.get('page_size') ?? 50)
    return HttpResponse.json(
      getOrders({
        status: (url.searchParams.get('status') ?? undefined) as
          | 'pending'
          | 'filled'
          | 'cancelled'
          | 'rejected'
          | undefined,
        symbol: url.searchParams.get('symbol') ?? undefined,
        side: (url.searchParams.get('side') ?? undefined) as 'buy' | 'sell' | undefined,
        date_from: url.searchParams.get('date_from') ?? undefined,
        date_to: url.searchParams.get('date_to') ?? undefined,
        page: Number.isFinite(page) ? page : 1,
        page_size: Number.isFinite(pageSize) ? pageSize : 50,
      }),
    )
  }),

  http.get('/api/sim/fills', async ({ request }) => {
    await delay(120)
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? 1)
    const pageSize = Number(url.searchParams.get('page_size') ?? 50)
    return HttpResponse.json(
      getFills({
        symbol: url.searchParams.get('symbol') ?? undefined,
        side: (url.searchParams.get('side') ?? undefined) as 'buy' | 'sell' | undefined,
        date_from: url.searchParams.get('date_from') ?? undefined,
        date_to: url.searchParams.get('date_to') ?? undefined,
        page: Number.isFinite(page) ? page : 1,
        page_size: Number.isFinite(pageSize) ? pageSize : 50,
      }),
    )
  }),

  http.post('/api/sim/orders/:orderId/cancel', async ({ params }) => {
    await delay(120)
    const result = cancelOrder(String(params.orderId))
    if (!result) {
      return HttpResponse.json(
        {
          code: 'SIM_ORDER_NOT_FOUND',
          message: '订单不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    return HttpResponse.json(result)
  }),

  http.post('/api/sim/settle', async () => {
    await delay(120)
    return HttpResponse.json(settleOrders())
  }),

  http.post('/api/sim/reset', async () => {
    await delay(120)
    return HttpResponse.json(resetAccount())
  }),

  http.get('/api/sim/config', async () => {
    await delay(90)
    return HttpResponse.json(getSimConfigStore())
  }),

  http.put('/api/sim/config', async ({ request }) => {
    await delay(120)
    const payload = (await request.json()) as Parameters<typeof setSimConfigStore>[0]
    return HttpResponse.json(setSimConfigStore(payload))
  }),

  http.get('/api/sim/portfolio', async () => {
    await delay(100)
    return HttpResponse.json(getPortfolio())
  }),

  http.get('/api/review/stats', async ({ request }) => {
    await delay(100)
    const url = new URL(request.url)
    return HttpResponse.json(
      getReview({
        date_from: url.searchParams.get('date_from') ?? undefined,
        date_to: url.searchParams.get('date_to') ?? undefined,
        date_axis: (url.searchParams.get('date_axis') as 'sell' | 'buy' | null) ?? undefined,
      }),
    )
  }),

  http.get('/api/ai/records', async () => {
    await delay(160)
    return HttpResponse.json({ items: getAIRecords() })
  }),

  http.delete('/api/ai/records', async ({ request }) => {
    await delay(140)
    const url = new URL(request.url)
    const symbol = url.searchParams.get('symbol') ?? ''
    const fetchedAt = url.searchParams.get('fetched_at') ?? ''
    const provider = url.searchParams.get('provider') ?? undefined
    return HttpResponse.json(deleteAIRecord(symbol, fetchedAt, provider))
  }),

  http.post('/api/ai/providers/test', async ({ request }) => {
    await delay(260)
    const payload = (await request.json()) as AIProviderTestRequest
    return HttpResponse.json(testAIProvider(payload))
  }),

  http.get('/api/config', async () => {
    await delay(90)
    return HttpResponse.json(getConfigStore())
  }),

  http.put('/api/config', async ({ request }) => {
    const payload = (await request.json()) as AppConfig
    await delay(120)
    return HttpResponse.json(setConfigStore(payload))
  }),

  http.get('/api/system/storage', async () => {
    await delay(100)
    return HttpResponse.json(getSystemStorageStore())
  }),

  http.post('/api/system/sync-market-data', async ({ request }) => {
    const payload = (await request.json()) as MarketDataSyncRequest
    await delay(400)
    return HttpResponse.json(syncMarketDataStore(payload))
  }),
]
