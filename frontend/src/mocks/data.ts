import dayjs from 'dayjs'
import type {
  AIAnalysisRecord,
  AIProviderTestRequest,
  AIProviderTestResponse,
  AppConfig,
  CandlePoint,
  IntradayPoint,
  PortfolioSnapshot,
  ReviewStats,
  ScreenerMode,
  ScreenerParams,
  ScreenerResult,
  ScreenerRunDetail,
  SignalScanMode,
  SignalResult,
  SignalsResponse,
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

const THEME_STAGES: ThemeStage[] = ['发酵中' as ThemeStage, '高潮' as ThemeStage, '退潮' as ThemeStage]

const candlesMap = new Map<string, CandlePoint[]>()
const runStore = new Map<string, ScreenerRunDetail>()
const annotationStore = new Map<string, StockAnnotation>()

let aiRecordsStore: AIAnalysisRecord[] = [
  {
    provider: 'openai',
    symbol: 'sz300750',
    name: '宁德时代',
    fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    source_urls: ['https://finance.eastmoney.com/', 'https://www.cls.cn/'],
    summary: '新能源主线保持活跃，回撤阶段承接较好。',
    conclusion: '发酵中',
    confidence: 0.78,
    breakout_date: dayjs().subtract(17, 'day').format('YYYY-MM-DD'),
    trend_bull_type: 'A_B 慢牛加速',
    theme_name: '固态电池',
    rise_reasons: ['20日量能斜率为正', '回调缩量且未破关键均线', '板块热度维持在发酵区间'],
  },
  {
    provider: 'openai',
    symbol: 'sh600519',
    name: '贵州茅台',
    fetched_at: dayjs().subtract(1, 'day').format('YYYY-MM-DD HH:mm:ss'),
    source_urls: ['https://www.cninfo.com.cn/'],
    summary: '消费龙头资金抱团明显，高位换手可控。',
    conclusion: '高潮',
    confidence: 0.66,
    breakout_date: dayjs().subtract(26, 'day').format('YYYY-MM-DD'),
    trend_bull_type: 'A 阶梯慢牛',
    theme_name: '高端消费',
    rise_reasons: ['龙头资金抱团', '回撤幅度有限', '基本面预期稳定'],
  },
]

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

function hashSeed(text: string) {
  return text.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
}

function mean(values: number[]) {
  if (values.length === 0) return 0
  return values.reduce((acc, value) => acc + value, 0) / values.length
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
    const seed = hashSeed(symbol)
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
  const seed = hashSeed(`${symbol}-${date}`)

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

    const volume = Math.max(1200, Math.floor(4000 + Math.sin((index + seed) / 8) * 1300 + (seed % 7) * 180))
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

function createMockSymbol(index: number) {
  const market = index % 2 === 0 ? 'sh' : 'sz'
  const code = `${100000 + index}`.padStart(6, '0').slice(-6)
  return `${market}${code}`
}

function createMockName(index: number) {
  const sectors = ['科技', '医药', '消费', '金融', '能源', '制造', '材料', '军工']
  return `${sectors[index % sectors.length]}样本${index + 1}`
}

function createPoolRecord(index: number, mode: ScreenerMode, stage: 'input' | 'step1' | 'step2' | 'step3'): ScreenerResult {
  const strictOffset = mode === 'strict' ? 0 : 0.015
  const baseRet = 0.06 + ((index % 200) / 1000) + strictOffset
  const trend: TrendClass = index % 17 === 0 ? 'B' : index % 5 === 0 ? 'A_B' : 'A'
  const stageLabel = index % 3 === 0 ? 'Early' : index % 3 === 1 ? 'Mid' : 'Late'
  const degraded = stage !== 'input' && index % 211 === 0
  const themeStage = THEME_STAGES[index % THEME_STAGES.length]

  return {
    symbol: createMockSymbol(index),
    name: createMockName(index),
    latest_price: Number((8 + (index % 220) * 0.9).toFixed(2)),
    day_change: Number((-2.1 + (index % 11) * 0.42).toFixed(2)),
    day_change_pct: Number((-0.03 + (index % 15) * 0.0045).toFixed(4)),
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
  const step1Pool = inputPool.slice(0, step1Count).map((row, index) => ({ ...row, score: 78 - (index % 30), labels: ['活跃强势池'] }))
  const step2Pool = step1Pool.slice(0, step2Count).map((row, index) => ({ ...row, score: 82 - (index % 28), labels: ['图形待确认'] }))
  const step3Pool = step2Pool.slice(0, step3Count).map((row, index) => ({ ...row, score: 86 - (index % 20), labels: ['量能健康'] }))

  const step4Pool = stockPool.slice(0, mode === 'strict' ? 5 : stockPool.length).map((item, index) => {
    const source = step3Pool[index] ?? step2Pool[index] ?? step1Pool[index] ?? inputPool[index]
    return {
      ...source,
      symbol: source?.symbol ?? item.symbol,
      name: source?.name ?? item.name,
      trend_class: item.trend,
      stage: item.stage,
      theme_stage: THEME_STAGES[index % THEME_STAGES.length],
      labels: ['题材发酵', '待买观察'],
      score: 90 - index,
      ai_confidence: 0.62 + index * 0.05,
    }
  })

  const detail: ScreenerRunDetail = {
    run_id: runId,
    created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    params,
    step_summary: {
      input_count: inputCount,
      step1_count: step1Count,
      step2_count: step2Count,
      step3_count: step3Count,
      step4_count: step4Pool.length,
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
    results: step4Pool,
    degraded: step4Pool.some((item) => item.degraded),
    degraded_reason: step4Pool.some((item) => item.degraded) ? 'PARTIAL_FLOAT_SHARES_FROM_CACHE' : undefined,
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
    suggest_stage: (base?.stage ?? 'Mid') as StockAnalysis['suggest_stage'],
    suggest_trend_class: (base?.trend ?? 'Unknown') as TrendClass,
    confidence: 0.74,
    reason: '均线结构稳定，回调量能可控，板块热度仍在发酵。',
    theme_stage: ('发酵中' as ThemeStage),
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

export function getSignals(params?: {
  mode?: SignalScanMode
  window_days?: number
  min_score?: number
  require_sequence?: boolean
  min_event_count?: number
}): SignalsResponse {
  const raw: Array<{ symbol: string; name: string; trigger_reason: string; signals: Array<'A' | 'B' | 'C'> }> = [
    { symbol: 'sz300750', name: '宁德时代', trigger_reason: '突破前高后缩量回踩确认', signals: ['A', 'B'] },
    { symbol: 'sh601899', name: '紫金矿业', trigger_reason: '板块分歧后转一致', signals: ['A', 'C'] },
    { symbol: 'sh600519', name: '贵州茅台', trigger_reason: 'MA10回踩确认', signals: ['A'] },
  ]
  const mode = params?.mode ?? 'trend_pool'
  const minScore = params?.min_score ?? 60
  const minEventCount = params?.min_event_count ?? 1
  const requireSequence = params?.require_sequence ?? false

  const items: SignalResult[] = raw.map((item, index) => {
    const resolved = resolveSignalPriority(item.signals)
    const wyEvents = ['SC', 'AR', 'ST', 'SOS', 'LPS'].slice(0, 3 + (index % 3))
    const wyRisk = index === 1 ? ['UTAD'] : []
    const score = 70 + (2 - index) * 8 - wyRisk.length * 6
    return {
      symbol: item.symbol,
      name: item.name,
      primary_signal: resolved.primary ?? 'C',
      secondary_signals: resolved.secondary,
      trigger_date: dayjs().subtract(index, 'day').format('YYYY-MM-DD'),
      expire_date: dayjs().add(2 - index, 'day').format('YYYY-MM-DD'),
      trigger_reason: item.trigger_reason,
      priority: resolved.primary === 'B' ? 3 : resolved.primary === 'A' ? 2 : 1,
      wyckoff_phase: index === 0 ? '吸筹D' : index === 1 ? '派发A' : '吸筹B',
      wyckoff_signal: wyEvents[wyEvents.length - 1] ?? '',
      structure_hhh: index === 0 ? 'HH|HL|HC' : index === 1 ? 'HH|-|-' : '-|HL|-',
      wy_event_count: wyEvents.length,
      wy_sequence_ok: index !== 2,
      entry_quality_score: score,
      wy_events: wyEvents,
      wy_risk_events: wyRisk,
      phase_hint: index === 1 ? '出现派发迹象，建议降低仓位并谨慎追高。' : '结构偏强，可继续观察回踩承接。',
      scan_mode: mode,
      event_strength_score: 65 + index * 4,
      phase_score: 60 + index * 5,
      structure_score: 55 + index * 8,
      trend_score: 62 + index * 6,
      volatility_score: 58 + index * 4,
    }
  })

  const filtered = items.filter((row) => {
    if ((row.entry_quality_score ?? 0) < minScore) return false
    if ((row.wy_event_count ?? 0) < minEventCount) return false
    if (requireSequence && !row.wy_sequence_ok) return false
    return true
  })

  return {
    items: filtered,
    mode,
    generated_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    cache_hit: false,
    degraded: false,
    source_count: raw.length,
  }
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
  return aiRecordsStore
}

function guessTheme(symbol: string) {
  const themes = ['固态电池', '机器人', '算力应用', '高端消费', '有色资源', '创新药']
  return themes[hashSeed(symbol) % themes.length]
}

function inferTrendBullType(trend: TrendClass) {
  if (trend === 'A') return 'A 阶梯慢牛'
  if (trend === 'A_B') return 'A_B 慢牛加速'
  if (trend === 'B') return 'B 脉冲涨停牛'
  return 'Unknown'
}

export function analyzeStockWithAI(symbol: string): AIAnalysisRecord {
  const base = stockPool.find((item) => item.symbol === symbol)
  const candles = ensureCandles(symbol)
  const latest = candles[candles.length - 1]
  const start20 = candles[Math.max(0, candles.length - 20)]
  const ret20 = latest && start20 ? (latest.close - start20.close) / Math.max(start20.close, 0.01) : 0
  const volumes20 = candles.slice(-20).map((item) => item.volume)
  const recentVolume = mean(volumes20.slice(-5))
  const prevVolume = mean(volumes20.slice(0, 5))

  const trend = base?.trend ?? (ret20 > 0.25 ? 'A_B' : 'A')
  const conclusion = ret20 > 0.45 ? '高潮' : ret20 > 0.05 ? '发酵中' : 'Unknown'
  const confidence = ret20 > 0.45 ? 0.74 : 0.67

  const record: AIAnalysisRecord = {
    provider: configStore.ai_provider,
    symbol,
    name: base?.name ?? symbol.toUpperCase(),
    fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    source_urls: configStore.ai_sources
      .filter((item) => item.enabled)
      .slice(0, 4)
      .map((item) => item.url),
    summary: `已完成 ${base?.name ?? symbol} 的题材与量价联合分析：近20日涨幅 ${(ret20 * 100).toFixed(2)}%，建议结合分时承接确认节奏。`,
    conclusion,
    confidence,
    breakout_date: dayjs().subtract(12 + (hashSeed(symbol) % 10), 'day').format('YYYY-MM-DD'),
    trend_bull_type: inferTrendBullType(trend),
    theme_name: guessTheme(symbol),
    rise_reasons: [
      recentVolume >= prevVolume ? '近端量能维持放大，资金活跃' : '量能趋稳，等待二次放量确认',
      ret20 > 0.1 ? '价格中枢上移，趋势结构保持多头' : '价格仍在构建底部区间',
      conclusion === '高潮' ? '题材一致性较高，但需防止高位波动' : '题材仍有扩散空间，可继续跟踪',
    ],
  }

  aiRecordsStore = [record, ...aiRecordsStore].slice(0, 200)
  return record
}

export function deleteAIRecord(symbol: string, fetchedAt: string, provider?: string) {
  const before = aiRecordsStore.length
  aiRecordsStore = aiRecordsStore.filter((item) => {
    if (item.symbol !== symbol) return true
    if (item.fetched_at !== fetchedAt) return true
    if (provider && item.provider !== provider) return true
    return false
  })
  return {
    deleted: aiRecordsStore.length < before,
    remaining: aiRecordsStore.length,
  }
}

export function testAIProvider(payload: AIProviderTestRequest): AIProviderTestResponse {
  const hasCredential =
    payload.provider.api_key.trim().length > 0
    || payload.provider.api_key_path.trim().length > 0
    || payload.fallback_api_key.trim().length > 0
    || payload.fallback_api_key_path.trim().length > 0

  if (!payload.provider.base_url.trim() || !payload.provider.model.trim()) {
    return {
      ok: false,
      provider_id: payload.provider.id,
      latency_ms: 0,
      message: '缺少 base_url 或 model',
      error_code: 'INVALID_PROVIDER_CONFIG',
    }
  }

  if (!hasCredential) {
    return {
      ok: false,
      provider_id: payload.provider.id,
      latency_ms: 0,
      message: '缺少 API 凭证，请填写 api_key 或 api_key_path',
      error_code: 'AI_KEY_MISSING',
    }
  }

  return {
    ok: true,
    provider_id: payload.provider.id,
    latency_ms: 120,
    message: '连接成功，耗时 120ms',
  }
}

export function getConfigStore() {
  return configStore
}

export function setConfigStore(payload: AppConfig) {
  configStore = payload
  return configStore
}
