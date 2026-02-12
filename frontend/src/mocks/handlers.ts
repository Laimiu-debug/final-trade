import { delay, http, HttpResponse } from 'msw'
import {
  createOrder,
  createScreenerRun,
  getAIRecords,
  getAnalysis,
  getCandlePayload,
  getIntradayPayload,
  getConfigStore,
  getPortfolio,
  getReview,
  getScreenerRun,
  getSignals,
  saveAnnotation,
  setConfigStore,
} from '@/mocks/data'
import type { AppConfig, ScreenerParams, StockAnnotation } from '@/types/contracts'

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

  http.get('/api/signals', async () => {
    await delay(120)
    return HttpResponse.json({ items: getSignals() })
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

  http.get('/api/sim/portfolio', async () => {
    await delay(100)
    return HttpResponse.json(getPortfolio())
  }),

  http.get('/api/review/stats', async () => {
    await delay(100)
    return HttpResponse.json(getReview())
  }),

  http.get('/api/ai/records', async () => {
    await delay(160)
    return HttpResponse.json({ items: getAIRecords() })
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
]
