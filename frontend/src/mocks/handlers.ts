import { delay, http, HttpResponse } from 'msw'
import {
  analyzeStockWithAI,
  cancelOrder,
  createReviewTagStore,
  createOrder,
  createScreenerRun,
  deleteDailyReviewStore,
  deleteReviewTagStore,
  deleteWeeklyReviewStore,
  deleteAIRecord,
  getDailyReviewStore,
  getDailyReviewsStore,
  getFills,
  getAIRecords,
  getAnalysis,
  getMarketNewsStore,
  getCandlePayload,
  getIntradayPayload,
  getConfigStore,
  getOrders,
  getPortfolio,
  getReview,
  getReviewFillTagStore,
  getReviewFillTagsStore,
  getReviewTagStatsStore,
  getReviewTagsStore,
  getSimConfigStore,
  getLatestScreenerRunStore,
  getScreenerRun,
  getSignals,
  getSystemStorageStore,
  getWeeklyReviewStore,
  getWeeklyReviewsStore,
  resetAccount,
  saveAnnotation,
  setSimConfigStore,
  syncMarketDataStore,
  settleOrders,
  setConfigStore,
  testAIProvider,
  runBacktestStore,
  updateReviewFillTagStore,
  upsertDailyReviewStore,
  upsertWeeklyReviewStore,
} from '@/mocks/data'
import type {
  AIProviderTestRequest,
  AppConfig,
  BacktestRunRequest,
  BacktestResponse,
  BoardFilter,
  DailyReviewPayload,
  MarketDataSyncRequest,
  ReviewTagCreateRequest,
  ReviewTagType,
  ScreenerParams,
  StockAnnotation,
  TradeFillTagUpdateRequest,
  WeeklyReviewPayload,
} from '@/types/contracts'

type MockBacktestTask = {
  status: 'running' | 'succeeded'
  poll_count: number
  result: BacktestResponse
}

const mockBacktestTaskStore = new Map<string, MockBacktestTask>()

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

  http.get('/api/screener/latest-run', async () => {
    await delay(220)
    const run = getLatestScreenerRunStore()
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
    const boardFilters = Array.from(
      new Set(
        url.searchParams
          .getAll('board_filters')
          .flatMap((item) => item.split(','))
          .map((item) => item.trim())
          .filter(
            (item): item is BoardFilter =>
              item === 'main' || item === 'gem' || item === 'star' || item === 'beijing' || item === 'st',
          ),
      ),
    )
    const refresh = url.searchParams.get('refresh') === 'true'
    const windowDays = Number(url.searchParams.get('window_days') ?? 60)
    const minScore = Number(url.searchParams.get('min_score') ?? 60)
    const requireSequence = url.searchParams.get('require_sequence') === 'true'
    const minEventCount = Number(url.searchParams.get('min_event_count') ?? 1)
    return HttpResponse.json(
      getSignals({
        mode,
        board_filters: boardFilters,
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

  http.post('/api/backtest/run', async ({ request }) => {
    await delay(220)
    const payload = (await request.json()) as BacktestRunRequest
    return HttpResponse.json(runBacktestStore(payload))
  }),

  http.post('/api/backtest/tasks', async ({ request }) => {
    await delay(120)
    const payload = (await request.json()) as BacktestRunRequest
    const taskId = `bt_mock_${Date.now()}_${Math.floor(Math.random() * 10000)}`
    mockBacktestTaskStore.set(taskId, {
      status: 'running',
      poll_count: 0,
      result: runBacktestStore(payload),
    })
    return HttpResponse.json({ task_id: taskId })
  }),

  http.get('/api/backtest/tasks/:taskId', async ({ params }) => {
    await delay(120)
    const taskId = String(params.taskId)
    const task = mockBacktestTaskStore.get(taskId)
    if (!task) {
      return HttpResponse.json(
        {
          code: 'BACKTEST_TASK_NOT_FOUND',
          message: '回测任务不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    task.poll_count += 1
    if (task.status === 'running' && task.poll_count >= 2) {
      task.status = 'succeeded'
    }
    if (task.status === 'running') {
      return HttpResponse.json({
        task_id: taskId,
        status: 'running',
        progress: {
          mode: 'daily',
          current_date: task.result.range.date_from,
          processed_dates: 1,
          total_dates: 2,
          percent: 50,
          message: '滚动筛选进度 1/2',
          warning: null,
          started_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      })
    }
    return HttpResponse.json({
      task_id: taskId,
      status: 'succeeded',
      progress: {
        mode: 'daily',
        current_date: task.result.range.date_to,
        processed_dates: 2,
        total_dates: 2,
        percent: 100,
        message: '回测完成。',
        warning: null,
        started_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      result: task.result,
      error: null,
    })
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

  http.get('/api/review/daily', async ({ request }) => {
    await delay(100)
    const url = new URL(request.url)
    return HttpResponse.json(
      getDailyReviewsStore({
        date_from: url.searchParams.get('date_from') ?? undefined,
        date_to: url.searchParams.get('date_to') ?? undefined,
      }),
    )
  }),

  http.get('/api/review/daily/:date', async ({ params }) => {
    await delay(80)
    const row = getDailyReviewStore(String(params.date))
    if (!row) {
      return HttpResponse.json(
        {
          code: 'REVIEW_DAILY_NOT_FOUND',
          message: '日复盘不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    return HttpResponse.json(row)
  }),

  http.put('/api/review/daily/:date', async ({ request, params }) => {
    await delay(120)
    const payload = (await request.json()) as DailyReviewPayload
    return HttpResponse.json(upsertDailyReviewStore(String(params.date), payload))
  }),

  http.delete('/api/review/daily/:date', async ({ params }) => {
    await delay(80)
    return HttpResponse.json(deleteDailyReviewStore(String(params.date)))
  }),

  http.get('/api/review/weekly', async ({ request }) => {
    await delay(100)
    const url = new URL(request.url)
    const yearRaw = url.searchParams.get('year')
    const year = yearRaw ? Number(yearRaw) : undefined
    return HttpResponse.json(getWeeklyReviewsStore({ year: Number.isFinite(year as number) ? year : undefined }))
  }),

  http.get('/api/review/weekly/:weekLabel', async ({ params }) => {
    await delay(80)
    const row = getWeeklyReviewStore(String(params.weekLabel))
    if (!row) {
      return HttpResponse.json(
        {
          code: 'REVIEW_WEEKLY_NOT_FOUND',
          message: '周复盘不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    return HttpResponse.json(row)
  }),

  http.put('/api/review/weekly/:weekLabel', async ({ request, params }) => {
    await delay(120)
    const payload = (await request.json()) as WeeklyReviewPayload
    return HttpResponse.json(upsertWeeklyReviewStore(String(params.weekLabel), payload))
  }),

  http.delete('/api/review/weekly/:weekLabel', async ({ params }) => {
    await delay(80)
    return HttpResponse.json(deleteWeeklyReviewStore(String(params.weekLabel)))
  }),

  http.get('/api/review/tags', async () => {
    await delay(80)
    return HttpResponse.json(getReviewTagsStore())
  }),

  http.post('/api/review/tags/:tagType', async ({ request, params }) => {
    await delay(100)
    const payload = (await request.json()) as ReviewTagCreateRequest
    const tagType = String(params.tagType) as ReviewTagType
    return HttpResponse.json(createReviewTagStore(tagType, payload))
  }),

  http.delete('/api/review/tags/:tagType/:tagId', async ({ params }) => {
    await delay(100)
    const tagType = String(params.tagType) as ReviewTagType
    return HttpResponse.json(deleteReviewTagStore(tagType, String(params.tagId)))
  }),

  http.get('/api/review/fill-tags', async () => {
    await delay(80)
    return HttpResponse.json(getReviewFillTagsStore())
  }),

  http.get('/api/review/fill-tags/:orderId', async ({ params }) => {
    await delay(80)
    const row = getReviewFillTagStore(String(params.orderId))
    if (!row) {
      return HttpResponse.json(
        {
          code: 'REVIEW_FILL_TAG_NOT_FOUND',
          message: '成交标签不存在',
          trace_id: `${Date.now()}`,
        },
        { status: 404 },
      )
    }
    return HttpResponse.json(row)
  }),

  http.put('/api/review/fill-tags/:orderId', async ({ request, params }) => {
    await delay(100)
    const payload = (await request.json()) as TradeFillTagUpdateRequest
    const updated = updateReviewFillTagStore(String(params.orderId), payload)
    if (!updated) {
      return HttpResponse.json(
        {
          code: 'REVIEW_FILL_TAG_INVALID',
          message: 'order_id not found in fill records',
          trace_id: `${Date.now()}`,
        },
        { status: 400 },
      )
    }
    return HttpResponse.json(updated)
  }),

  http.get('/api/review/tag-stats', async ({ request }) => {
    await delay(100)
    const url = new URL(request.url)
    return HttpResponse.json(
      getReviewTagStatsStore({
        date_from: url.searchParams.get('date_from') ?? undefined,
        date_to: url.searchParams.get('date_to') ?? undefined,
      }),
    )
  }),

  http.get('/api/market/news', async ({ request }) => {
    await delay(140)
    const url = new URL(request.url)
    const limitRaw = Number(url.searchParams.get('limit') ?? 20)
    const ageHoursRaw = Number(url.searchParams.get('age_hours') ?? 72)
    const ageHours = ageHoursRaw === 24 || ageHoursRaw === 48 || ageHoursRaw === 72 ? ageHoursRaw : 72
    const refresh = (url.searchParams.get('refresh') ?? '').toLowerCase() === 'true'
    const sourceDomainsRaw = url.searchParams.get('source_domains') ?? ''
    const sourceDomains = sourceDomainsRaw
      .replace(/;/g, ',')
      .replace(/\|/g, ',')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    return HttpResponse.json(
      getMarketNewsStore({
        query: url.searchParams.get('query') ?? undefined,
        symbol: url.searchParams.get('symbol') ?? undefined,
        source_domains: sourceDomains,
        age_hours: ageHours,
        refresh,
        limit: Number.isFinite(limitRaw) ? limitRaw : 20,
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
