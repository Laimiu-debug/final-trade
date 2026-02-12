import dayjs from 'dayjs'
import type {
  AIAnalysisRecord,
  AppConfig,
  CandlePoint,
  IntradayPoint,
  PortfolioSnapshot,
  ReviewStats,
  ScreenerMode,
  ScreenerParams,
  ScreenerResult,
  ScreenerRunDetail,
  SignalResult,
  StockAnalysis,
  StockAnnotation,
  ThemeStage,
  TradeRecord,
  TrendClass,
} from '@/types/contracts'
import { resolveSignalPriority } from '@/shared/utils/signals'

const stockPool: Array<{ symbol: string; name: string; trend: TrendClass; stage: 'Early' | 'Mid' | 'Late' }> = [
  { symbol: 'sh600519', name: '贵州茅台', trend: 'A', stage: 'Mid' },
  { symbol: 'sz300750', name: '宁德时代', trend: 'A_B', stage: 'Early' },
  { symbol: 'sh601899', name: '紫金矿业', trend: 'A', stage: 'Mid' },
  { symbol: 'sz002594', name: '比亚迪', trend: 'A_B', stage: 'Mid' },
  { symbol: 'sh600030', name: '中信证券', trend: 'A', stage: 'Early' },
  { symbol: 'sz000333', name: '美的集团', trend: 'A', stage: 'Late' },
  { symbol: 'sh688041', name: '海光信息', trend: 'B', stage: 'Late' },
  { symbol: 'sz002230', name: '科大讯飞', trend: 'A_B', stage: 'Mid' },
]

const candlesMap = new Map<string, CandlePoint[]>()
const runStore = new Map<string, ScreenerRunDetail>()
const annotationStore = new Map<string, StockAnnotation>()

let configStore: AppConfig = {
  tdx_data_path: 'D:\\new_tdx\\vipdoc',
  markets: ['sh', 'sz'],
  return_window_days: 40,
  top_n: 500,
  turnover_threshold: 0.05,
  amount_threshold: 5e8,
  amplitude_threshold: 0.03,
  initial_capital: 1_000_000,
  ai_provider: 'openai',
  ai_timeout_sec: 10,
  ai_retry_count: 2,
  api_key: '',
  api_key_path: '%USERPROFILE%\\.tdx-trend\\app.config.json',
  ai_providers: [
    {
      id: 'openai',
      label: 'OpenAI',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
      api_key: '',
      api_key_path: '%USERPROFILE%\\.tdx-trend\\openai.key',
      enabled: true,
    },
    {
      id: 'qwen',
      label: 'Qwen',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      model: 'qwen-plus',
      api_key: '',
      api_key_path: '%USERPROFILE%\\.tdx-trend\\qwen.key',
      enabled: true,
    },
    {
      id: 'deepseek',
      label: 'DeepSeek',
      base_url: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
      api_key: '',
      api_key_path: '%USERPROFILE%\\.tdx-trend\\deepseek.key',
      enabled: true,
    },
    {
      id: 'ernie',
      label: 'ERNIE',
      base_url: 'https://qianfan.baidubce.com/v2',
      model: 'ernie-4.0-turbo',
      api_key: '',
      api_key_path: '%USERPROFILE%\\.tdx-trend\\ernie.key',
      enabled: false,
    },
    {
      id: 'custom-1',
      label: '自定义Provider',
      base_url: 'https://your-provider.example.com/v1',
      model: 'custom-model',
      api_key: '',
      api_key_path: '%USERPROFILE%\\.tdx-trend\\custom.key',
      enabled: false,
    },
  ],
  ai_sources: [
    { id: 'eastmoney', name: '东方财富新闻', url: 'https://finance.eastmoney.com/', enabled: true },
    { id: 'juchao', name: '巨潮资讯', url: 'http://www.cninfo.com.cn/', enabled: true },
    { id: 'cls', name: '财联社', url: 'https://www.cls.cn/', enabled: true },
    { id: 'xueqiu', name: '雪球', url: 'https://xueqiu.com/', enabled: false },
  ],
}

function genCandles(seed: number, startPrice = 40): CandlePoint[] {
  const points: CandlePoint[] = []
  let close = startPrice
  for (let i = 119; i >= 0; i -= 1) {
    const date = dayjs().subtract(i, 'day').format('YYYY-MM-DD')
    const drift = Math.sin((i + seed) / 9) * 0.9 + (seed % 3 === 0 ? 0.2 : 0.35)
    const open = Math.max(5, close + drift * 0.35)
    const high = open + Math.abs(drift) * 1.8 + 0.6
    const low = Math.max(1, open - Math.abs(drift) * 1.4 - 0.5)
    close = Number((low + (high - low) * 0.68).toFixed(2))
    points.push({
      time: date,
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close,
      volume: Math.floor(2_000_000 + (Math.cos((i + seed) / 7) + 1.4) * 1_700_000),
      amount: Math.floor(close * 100_000_000),
      price_source: seed % 4 === 0 ? 'approx' : 'vwap',
    })
  }
  return points
}

function ensureCandles(symbol: string) {
  if (!candlesMap.has(symbol)) {
    const seed = symbol
      .split('')
      .map((char) => char.charCodeAt(0))
      .reduce((acc, cur) => acc + cur, 0)
    candlesMap.set(symbol, genCandles(seed, 20 + (seed % 70)))
  }
  return candlesMap.get(symbol) ?? []
}

function buildIntradayTimeAxis() {
  const morning = Array.from({ length: 120 }, (_, i) => {
    const total = 9 * 60 + 30 + i
    const hh = Math.floor(total / 60)
    const mm = total % 60
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
  })
  const afternoon = Array.from({ length: 120 }, (_, i) => {
    const total = 13 * 60 + i
    const hh = Math.floor(total / 60)
    const mm = total % 60
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
  })
  return [...morning, ...afternoon]
}

function genIntradayPoints(symbol: string, date: string, basePrice: number): IntradayPoint[] {
  const times = buildIntradayTimeAxis()
  const seed = `${symbol}-${date}`
    .split('')
    .map((char) => char.charCodeAt(0))
    .reduce((acc, cur) => acc + cur, 0)

  const points: IntradayPoint[] = []
  let price = basePrice
  let turnover = 0
  let totalVolume = 0

  times.forEach((time, index) => {
    const wave = Math.sin((index + seed) / 10) * 0.22
    const drift = (index / times.length - 0.5) * (seed % 3 === 0 ? 0.5 : 0.28)
    const micro = Math.cos((index + seed) / 5) * 0.06
    price = Math.max(1, price + wave * 0.05 + drift * 0.03 + micro)
    const roundedPrice = Number(price.toFixed(2))

    const volume = Math.max(
      1200,
      Math.floor(4000 + Math.sin((index + seed) / 8) * 1300 + (seed % 7) * 180),
    )
    totalVolume += volume
    turnover += roundedPrice * volume
    const avgPrice = Number((turnover / totalVolume).toFixed(2))

    points.push({
      time,
      price: roundedPrice,
      avg_price: avgPrice,
      volume,
      price_source: index % 79 === 0 ? 'approx' : 'vwap',
    })
  })

  return points
}

function buildResult(input: typeof stockPool[number], index: number, mode: ScreenerMode): ScreenerResult {
  const modeOffset = mode === 'strict' ? 0 : 4
  const score = 86 - index * 4 + modeOffset
  const degraded = input.symbol === 'sz002230'
  const themeStageList: ThemeStage[] = ['发酵中', '高潮', '退潮']
  const themeStage = themeStageList[index % themeStageList.length]
  return {
    symbol: input.symbol,
    name: input.name,
    latest_price: Number((42 + index * 3.6).toFixed(2)),
    day_change: Number(((-1.2 + (index % 5) * 0.8)).toFixed(2)),
    day_change_pct: Number(((-0.018 + (index % 6) * 0.009)).toFixed(4)),
    score,
    ret40: 0.22 + index * 0.031,
    turnover20: 0.053 + index * 0.008,
    amount20: 580_000_000 + index * 80_000_000,
    amplitude20: 0.032 + index * 0.003,
    retrace20: 0.06 + index * 0.02,
    pullback_days: 1 + (index % 4),
    ma10_above_ma20_days: 8 + (index % 7),
    ma5_above_ma10_days: 6 + (index % 5),
    price_vs_ma20: 0.008 + (index % 6) * 0.005,
    vol_slope20: 0.14 + (index % 8) * 0.05,
    up_down_volume_ratio: 1.26 + (index % 6) * 0.1,
    pullback_volume_ratio: 0.5 + (index % 5) * 0.07,
    has_blowoff_top: index % 21 === 0,
    has_divergence_5d: index % 13 === 0,
    has_upper_shadow_risk: index % 17 === 0,
    ai_confidence: 0.63 + (index % 4) * 0.08,
    theme_stage: themeStage,
    trend_class: input.trend,
    stage: input.stage,
    labels: ['活跃', input.trend === 'B' ? '高波动' : '趋势延续'],
    reject_reasons: [],
    degraded,
    degraded_reason: degraded ? 'FLOAT_SHARES_CACHE_USED' : undefined,
  }
}

function createMockSymbol(index: number) {
  const market = index % 2 === 0 ? 'sh' : 'sz'
  const code = `${100000 + index}`.padStart(6, '0').slice(-6)
  return `${market}${code}`
}

function createMockName(index: number) {
  const sectors = ['科技', '医药', '消费', '金融', '能源', '制造', '材料', '军工']
  return `${sectors[index % sectors.length]}样本${index + 1}`
}

function createPoolRecord(index: number, mode: ScreenerMode, stage: 'input' | 'step1' | 'step2' | 'step3' | 'step4'): ScreenerResult {
  const strictOffset = mode === 'strict' ? 0 : 0.015
  const baseRet = 0.06 + ((index % 200) / 1000) + strictOffset
  const trend: TrendClass = index % 17 === 0 ? 'B' : index % 5 === 0 ? 'A_B' : 'A'
  const stageLabel = index % 3 === 0 ? 'Early' : index % 3 === 1 ? 'Mid' : 'Late'
  const degraded = stage !== 'input' && index % 211 === 0
  const themeStageList: ThemeStage[] = ['发酵中', '高潮', '退潮']
  const themeStage = themeStageList[index % themeStageList.length]
  return {
    symbol: createMockSymbol(index),
    name: createMockName(index),
    latest_price: Number((8 + (index % 220) * 0.9).toFixed(2)),
    day_change: Number(((-2.1 + (index % 11) * 0.42)).toFixed(2)),
    day_change_pct: Number(((-0.03 + (index % 15) * 0.0045)).toFixed(4)),
    score: Math.max(20, 92 - (index % 70)),
    ret40: baseRet,
    turnover20: 0.035 + (index % 25) * 0.002,
    amount20: 220_000_000 + (index % 150) * 18_000_000,
    amplitude20: 0.025 + (index % 12) * 0.002,
    retrace20: 0.03 + (index % 22) * 0.01,
    pullback_days: 1 + (index % 6),
    ma10_above_ma20_days: 4 + (index % 11),
    ma5_above_ma10_days: 2 + (index % 9),
    price_vs_ma20: -0.03 + (index % 13) * 0.008,
    vol_slope20: -0.2 + (index % 20) * 0.07,
    up_down_volume_ratio: 0.9 + (index % 18) * 0.06,
    pullback_volume_ratio: 0.45 + (index % 11) * 0.08,
    has_blowoff_top: stage !== 'input' && index % 31 === 0,
    has_divergence_5d: stage !== 'input' && index % 17 === 0,
    has_upper_shadow_risk: stage !== 'input' && index % 19 === 0,
    ai_confidence: 0.4 + (index % 11) * 0.05,
    theme_stage: themeStage,
    trend_class: trend,
    stage: stageLabel,
    labels: stage === 'input' ? ['全市场候选'] : ['活跃', '趋势延续'],
    reject_reasons: [],
    degraded,
    degraded_reason: degraded ? 'PARTIAL_CACHE_FALLBACK' : undefined,
  }
}

function createPoolRange(start: number, count: number, mode: ScreenerMode, stage: 'input' | 'step1' | 'step2' | 'step3') {
  return Array.from({ length: count }, (_, offset) => createPoolRecord(start + offset, mode, stage))
}

export function createScreenerRun(params: ScreenerParams) {
  const runId = `${Date.now()}-${Math.floor(Math.random() * 10000)}`
  const mode = params.mode
  const inputCount = 5100
  const step1Count = 400
  const step2Count = mode === 'strict' ? 68 : 92
  const step3Count = mode === 'strict' ? 26 : 37

  const inputPool = createPoolRange(0, inputCount, mode, 'input')
  const step1Pool = inputPool.slice(0, step1Count).map((row, index) => ({
    ...row,
    score: 78 - (index % 30),
    labels: ['活跃强势池'],
  }))
  const step2Pool = step1Pool.slice(0, step2Count).map((row, index) => ({
    ...row,
    score: 82 - (index % 28),
    labels: ['图形待确认'],
  }))
  const step3Pool = step2Pool.slice(0, step3Count).map((row, index) => ({
    ...row,
    score: 86 - (index % 20),
    labels: ['量能健康'],
  }))

  const finalBase = mode === 'strict' ? stockPool.slice(0, 5) : stockPool
  const step4Pool = finalBase.map((item, index) => ({
    ...buildResult(item, index, mode),
    symbol: step3Pool[index]?.symbol ?? buildResult(item, index, mode).symbol,
    name: step3Pool[index]?.name ?? item.name,
    labels: ['题材发酵', '待买观察'],
  }))
  const results = step4Pool

  const detail: ScreenerRunDetail = {
    run_id: runId,
    created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    params,
    step_summary: {
      input_count: inputCount,
      step1_count: step1Count,
      step2_count: step2Count,
      step3_count: step3Count,
      step4_count: results.length,
      final_count: 0,
    },
    step_pools: {
      input: inputPool,
      step1: step1Pool,
      step2: step2Pool,
      step3: step3Pool,
      step4: step4Pool,
      final: [],
    },
    results,
    degraded: results.some((item) => item.degraded),
    degraded_reason: results.some((item) => item.degraded) ? 'PARTIAL_FLOAT_SHARES_FROM_CACHE' : undefined,
  }
  runStore.set(runId, detail)
  return detail
}

export function getScreenerRun(runId: string) {
  return runStore.get(runId)
}

export function getCandlePayload(symbol: string) {
  const candles = ensureCandles(symbol)
  const degraded = candles.some((point) => point.price_source === 'approx')
  return {
    symbol,
    candles,
    degraded,
    degraded_reason: degraded ? 'MINUTE_DATA_MISSING_PARTIAL' : undefined,
  }
}

export function getIntradayPayload(symbol: string, date: string) {
  const candles = ensureCandles(symbol)
  const fallbackDate = candles[candles.length - 1]?.time ?? dayjs().format('YYYY-MM-DD')
  const matched = candles.find((item) => item.time === date)
  const targetDate = matched ? date : fallbackDate
  const basePrice = matched?.close ?? candles[candles.length - 1]?.close ?? 20
  const points = genIntradayPoints(symbol, targetDate, basePrice)
  const degraded = points.some((point) => point.price_source === 'approx')

  return {
    symbol,
    date: targetDate,
    points,
    degraded,
    degraded_reason: degraded ? 'MINUTE_DATA_PARTIAL_APPROX' : undefined,
  }
}

export function getAnalysis(symbol: string): { analysis: StockAnalysis; annotation?: StockAnnotation } {
  const base = stockPool.find((stock) => stock.symbol === symbol)
  const analysis: StockAnalysis = {
    symbol,
    suggest_start_date: dayjs().subtract(53, 'day').format('YYYY-MM-DD'),
    suggest_stage: base?.stage ?? 'Mid',
    suggest_trend_class: base?.trend ?? 'Unknown',
    confidence: 0.74,
    reason: '均线结构稳定，回调量能可控，板块热度仍在发酵。',
    theme_stage: '发酵中',
    degraded: symbol === 'sz002230',
    degraded_reason: symbol === 'sz002230' ? 'AI_TIMEOUT_CACHE_FALLBACK' : undefined,
  }
  return {
    analysis,
    annotation: annotationStore.get(symbol),
  }
}

export function saveAnnotation(annotation: StockAnnotation) {
  annotationStore.set(annotation.symbol, annotation)
  return annotation
}

export function getSignals(): SignalResult[] {
  const raw: Array<{ symbol: string; name: string; trigger_reason: string; signals: Array<'A' | 'B' | 'C'> }> = [
    { symbol: 'sz300750', name: '宁德时代', trigger_reason: '突破新高后缩量回踩', signals: ['A', 'B'] },
    { symbol: 'sh601899', name: '紫金矿业', trigger_reason: '板块分歧后转一致', signals: ['A', 'C'] },
    { symbol: 'sh600519', name: '贵州茅台', trigger_reason: 'MA10回踩确认', signals: ['A'] },
  ]
  return raw.map((item, index) => {
    const resolved = resolveSignalPriority(item.signals)
    return {
      symbol: item.symbol,
      name: item.name,
      primary_signal: resolved.primary ?? 'C',
      secondary_signals: resolved.secondary,
      trigger_date: dayjs().subtract(index, 'day').format('YYYY-MM-DD'),
      expire_date: dayjs().add(2 - index, 'day').format('YYYY-MM-DD'),
      trigger_reason: item.trigger_reason,
      priority: resolved.primary === 'B' ? 3 : resolved.primary === 'A' ? 2 : 1,
    }
  })
}

export function createOrder(payload: {
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  signal_date: string
  submit_date: string
}) {
  const orderId = `ord-${Date.now()}`
  return {
    order: {
      order_id: orderId,
      symbol: payload.symbol,
      side: payload.side,
      quantity: payload.quantity,
      signal_date: payload.signal_date,
      submit_date: payload.submit_date,
      status: 'filled' as const,
    },
    fill: {
      order_id: orderId,
      symbol: payload.symbol,
      fill_date: payload.submit_date,
      fill_price: 86.35,
      price_source: 'vwap' as const,
      fee_commission: 5,
      fee_stamp_tax: payload.side === 'sell' ? 16.2 : 0,
      fee_transfer: 0.5,
    },
  }
}

export function getPortfolio(): PortfolioSnapshot {
  return {
    total_asset: 1_082_000,
    cash: 308_000,
    position_value: 774_000,
    positions: [
      {
        symbol: 'sz300750',
        name: '宁德时代',
        quantity: 1500,
        avg_cost: 165.3,
        current_price: 174.2,
        pnl_ratio: 0.0538,
        holding_days: 9,
      },
      {
        symbol: 'sh601899',
        name: '紫金矿业',
        quantity: 12000,
        avg_cost: 16.8,
        current_price: 17.6,
        pnl_ratio: 0.0476,
        holding_days: 14,
      },
    ],
  }
}

export function getReview(): { stats: ReviewStats; trades: TradeRecord[] } {
  return {
    stats: {
      win_rate: 0.62,
      total_return: 0.128,
      max_drawdown: 0.071,
      avg_pnl_ratio: 0.034,
    },
    trades: [
      {
        symbol: 'sz300750',
        buy_date: '2026-01-16',
        buy_price: 160.5,
        sell_date: '2026-01-23',
        sell_price: 172.4,
        holding_days: 7,
        pnl_amount: 17850,
        pnl_ratio: 0.074,
      },
      {
        symbol: 'sh601899',
        buy_date: '2026-01-08',
        buy_price: 15.6,
        sell_date: '2026-01-20',
        sell_price: 17.2,
        holding_days: 12,
        pnl_amount: 9600,
        pnl_ratio: 0.102,
      },
    ],
  }
}

export function getAIRecords(): AIAnalysisRecord[] {
  return [
    {
      provider: 'openai',
      symbol: 'sz300750',
      fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      source_urls: ['https://example.com/news/ev-1', 'https://example.com/forum/battery'],
      summary: '板块热度持续，头部与补涨梯队完整。',
      conclusion: '发酵中',
      confidence: 0.78,
    },
    {
      provider: 'openai',
      symbol: 'sh600519',
      fetched_at: dayjs().subtract(1, 'day').format('YYYY-MM-DD HH:mm:ss'),
      source_urls: ['https://example.com/news/consumption'],
      summary: '消费主线维持，成交稳定。',
      conclusion: '高潮',
      confidence: 0.66,
    },
  ]
}

export function getConfigStore() {
  return configStore
}

export function setConfigStore(payload: AppConfig) {
  configStore = payload
  return configStore
}
