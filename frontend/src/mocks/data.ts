import dayjs from 'dayjs'
import type {
  AIAnalysisRecord,
  AIProviderTestRequest,
  AIProviderTestResponse,
  AppConfig,
  BacktestResponse,
  BacktestRunRequest,
  BacktestTrade,
  CandlePoint,
  DailyReviewListResponse,
  DailyReviewPayload,
  DailyReviewRecord,
  IntradayPoint,
  MarketDataSyncRequest,
  MarketDataSyncResponse,
  MarketNewsResponse,
  PortfolioPosition,
  PortfolioSnapshot,
  ReviewResponse,
  ReviewTag,
  ReviewTagCreateRequest,
  ReviewTagStatsResponse,
  ReviewTagsPayload,
  ReviewTagType,
  ScreenerMode,
  ScreenerParams,
  ScreenerResult,
  ScreenerRunDetail,
  SimFillsResponse,
  SimOrdersResponse,
  SimResetResponse,
  SimSettleResponse,
  SimTradeFill,
  SimTradeOrder,
  SimTradingConfig,
  SignalScanMode,
  SignalResult,
  SignalsResponse,
  StockAnalysis,
  StockAnnotation,
  SystemStorageStatus,
  TradeFillTagAssignment,
  TradeFillTagUpdateRequest,
  WeeklyReviewListResponse,
  WeeklyReviewPayload,
  WeeklyReviewRecord,
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
let dailyReviewsStore: DailyReviewRecord[] = []
let weeklyReviewsStore: WeeklyReviewRecord[] = []
let fillTagStore: TradeFillTagAssignment[] = []
let reviewTagsStore: ReviewTagsPayload = {
  emotion: [
    { id: 'emotion-01', name: '冲动追高', color: 'red', created_at: '2026-01-01 00:00:00' },
    { id: 'emotion-02', name: '恐慌割肉', color: 'volcano', created_at: '2026-01-01 00:00:00' },
    { id: 'emotion-03', name: '理性建仓', color: 'blue', created_at: '2026-01-01 00:00:00' },
  ],
  reason: [
    { id: 'reason-01', name: '财报利好', color: 'geekblue', created_at: '2026-01-01 00:00:00' },
    { id: 'reason-02', name: '政策利好', color: 'magenta', created_at: '2026-01-01 00:00:00' },
    { id: 'reason-03', name: '技术突破', color: 'cyan', created_at: '2026-01-01 00:00:00' },
  ],
}

const marketNewsSeed: MarketNewsResponse['items'] = [
  {
    title: 'AI 算力板块午后拉升，多只核心股放量走强',
    url: 'https://finance.eastmoney.com/',
    snippet: '盘中资金回流算力与光模块方向，短线风险偏好明显提升。',
    pub_date: dayjs().subtract(1, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    source_name: '东方财富',
  },
  {
    title: '机器人产业链持续活跃，政策催化叠加订单预期',
    url: 'https://www.cls.cn/',
    snippet: '多家机构认为机器人板块景气度仍有向上空间，但需关注高位波动。',
    pub_date: dayjs().subtract(3, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    source_name: '财联社',
  },
  {
    title: '半导体设备公司披露业绩预告，行业景气延续分化',
    url: 'https://www.cninfo.com.cn/',
    snippet: '龙头公司盈利改善较快，二线标的估值修复节奏存在差异。',
    pub_date: dayjs().subtract(6, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    source_name: '巨潮资讯',
  },
  {
    title: 'A股三大指数震荡整理，成交额较前一日温和放大',
    url: 'https://finance.eastmoney.com/',
    snippet: '市场风格在成长与价值之间来回切换，热点轮动速度仍然较快。',
    pub_date: dayjs().subtract(10, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    source_name: '东方财富',
  },
  {
    title: '上周市场风格复盘：成长与价值轮动的节奏',
    url: 'https://finance.eastmoney.com/',
    snippet: '该文用于验证时效筛选，默认不应出现在 24h/48h 结果中。',
    pub_date: dayjs().subtract(96, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    source_name: '东方财富',
  },
]
let marketNewsCacheStore = new Map<string, { ts: number; items: MarketNewsResponse['items'] }>()
let marketNewsLastSuccess: MarketNewsResponse['items'] = []

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
  market_data_source: 'tdx_then_akshare',
  akshare_cache_dir: '%USERPROFILE%\\.tdx-trend\\akshare\\daily',
  markets: ['sh', 'sz'],
  return_window_days: 40,
  candles_window_bars: 120,
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

let simConfigStore: SimTradingConfig = {
  initial_capital: 1_000_000,
  commission_rate: 0.0003,
  min_commission: 5,
  stamp_tax_rate: 0.001,
  transfer_fee_rate: 0.00001,
  slippage_rate: 0,
}

let simCash = simConfigStore.initial_capital
let simOrdersStore: SimTradeOrder[] = []
let simFillsStore: SimTradeFill[] = []
let simLotsStore: Array<{
  symbol: string
  buy_date: string
  buy_price: number
  unit_cost: number
  quantity: number
  remaining: number
}> = []
let simClosedTradesStore: TradeRecord[] = []

function hashSeed(text: string) {
  return text.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
}

function mean(values: number[]) {
  if (values.length === 0) return 0
  return values.reduce((acc, value) => acc + value, 0) / values.length
}

function clamp(value: number, lower: number, upper: number) {
  return Math.max(lower, Math.min(upper, value))
}

function uniqueTokens(values: string[]) {
  const seen = new Set<string>()
  const result: string[] = []
  values.forEach((item) => {
    const token = item.trim()
    if (!token || seen.has(token)) return
    seen.add(token)
    result.push(token)
  })
  return result
}

function getWeekRangeFromLabel(weekLabel: string) {
  const match = weekLabel.match(/^(\d{4})-W(\d{2})$/)
  if (!match) {
    const today = dayjs()
    return { start_date: today.startOf('week').format('YYYY-MM-DD'), end_date: today.endOf('week').format('YYYY-MM-DD') }
  }
  const year = Number(match[1])
  const week = Number(match[2])
  const jan4 = dayjs(`${year}-01-04`)
  const firstMonday = jan4.subtract((jan4.day() + 6) % 7, 'day')
  const start = firstMonday.add((week - 1) * 7, 'day')
  return {
    start_date: start.format('YYYY-MM-DD'),
    end_date: start.add(6, 'day').format('YYYY-MM-DD'),
  }
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

export function getLatestScreenerRunStore() {
  let latest: ScreenerRunDetail | undefined
  for (const detail of runStore.values()) {
    latest = detail
  }
  if (latest) {
    return latest
  }

  const seeded = createScreenerRun({
    markets: configStore.markets,
    mode: 'strict',
    as_of_date: dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
    return_window_days: configStore.return_window_days,
    top_n: configStore.top_n,
    turnover_threshold: configStore.turnover_threshold,
    amount_threshold: configStore.amount_threshold,
    amplitude_threshold: configStore.amplitude_threshold,
  })
  return seeded
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

function applyOrderFill(order: SimTradeOrder): SimTradeFill | null {
  const symbol = order.symbol
  const submitDate = order.submit_date
  const fillPrice = Number(order.estimated_price ?? 20)
  const grossAmount = fillPrice * order.quantity
  const commission = Math.max(grossAmount * simConfigStore.commission_rate, simConfigStore.min_commission)
  const stampTax = order.side === 'sell' ? grossAmount * simConfigStore.stamp_tax_rate : 0
  const transferFee = grossAmount * simConfigStore.transfer_fee_rate
  const totalFee = commission + stampTax + transferFee

  if (order.side === 'buy' && simCash < grossAmount + totalFee) {
    order.status = 'rejected'
    order.reject_reason = 'SIM_INSUFFICIENT_CASH'
    order.status_reason = 'SIM_INSUFFICIENT_CASH'
    order.cash_impact = 0
    order.filled_date = undefined
    return null
  }

  const available = simLotsStore.filter((lot) => lot.symbol === symbol).reduce((sum, lot) => sum + lot.remaining, 0)
  if (order.side === 'sell' && available < order.quantity) {
    order.status = 'rejected'
    order.reject_reason = 'SIM_INSUFFICIENT_POSITION'
    order.status_reason = 'SIM_INSUFFICIENT_POSITION'
    order.cash_impact = 0
    order.filled_date = undefined
    return null
  }

  const fill: SimTradeFill = {
    order_id: order.order_id,
    symbol,
    side: order.side,
    quantity: order.quantity,
    fill_date: submitDate,
    fill_price: fillPrice,
    price_source: 'vwap',
    gross_amount: Number(grossAmount.toFixed(4)),
    net_amount: Number((order.side === 'buy' ? -(grossAmount + totalFee) : grossAmount - totalFee).toFixed(4)),
    fee_commission: Number(commission.toFixed(4)),
    fee_stamp_tax: Number(stampTax.toFixed(4)),
    fee_transfer: Number(transferFee.toFixed(4)),
  }

  if (order.side === 'buy') {
    simCash -= grossAmount + totalFee
    simLotsStore.push({
      symbol,
      buy_date: submitDate,
      buy_price: fillPrice,
      unit_cost: (grossAmount + totalFee) / order.quantity,
      quantity: order.quantity,
      remaining: order.quantity,
    })
  } else {
    simCash += grossAmount - totalFee
    let remaining = order.quantity
    for (const lot of simLotsStore) {
      if (lot.symbol !== symbol || lot.remaining <= 0 || remaining <= 0) continue
      const take = Math.min(lot.remaining, remaining)
      const buyCost = lot.unit_cost * take
      const sellFeePart = totalFee * (take / order.quantity)
      const sellNet = fillPrice * take - sellFeePart
      const pnlAmount = sellNet - buyCost
      simClosedTradesStore.push({
        symbol,
        buy_date: lot.buy_date,
        buy_price: lot.buy_price,
        sell_date: submitDate,
        sell_price: fillPrice,
        quantity: take,
        holding_days: Math.max(0, dayjs(submitDate).diff(dayjs(lot.buy_date), 'day')),
        pnl_amount: Number(pnlAmount.toFixed(4)),
        pnl_ratio: buyCost > 0 ? Number((pnlAmount / buyCost).toFixed(6)) : 0,
      })
      lot.remaining -= take
      remaining -= take
    }
    simLotsStore = simLotsStore.filter((lot) => lot.remaining > 0)
  }

  simCash = Number(simCash.toFixed(4))
  order.status = 'filled'
  order.filled_date = submitDate
  order.reject_reason = undefined
  order.status_reason = undefined
  order.cash_impact = fill.net_amount
  simFillsStore = [fill, ...simFillsStore]
  return fill
}

export function createOrder(payload: {
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  signal_date: string
  submit_date: string
}) {
  const symbol = payload.symbol.trim().toLowerCase()
  const orderId = `ord-${Date.now()}-${Math.floor(Math.random() * 1000)}`
  const submitDate = payload.submit_date || dayjs().format('YYYY-MM-DD')
  const candles = ensureCandles(symbol)
  const latest = candles[candles.length - 1]
  const basePrice = latest?.open ?? latest?.close ?? 20
  const slippage = simConfigStore.slippage_rate
  const estimatedPrice = Number(
    (
      payload.side === 'buy'
        ? basePrice * (1 + slippage)
        : basePrice * (1 - slippage)
    ).toFixed(4),
  )
  const estimatedAmount = estimatedPrice * payload.quantity
  const estimatedCommission = Math.max(estimatedAmount * simConfigStore.commission_rate, simConfigStore.min_commission)
  const estimatedStamp = payload.side === 'sell' ? estimatedAmount * simConfigStore.stamp_tax_rate : 0
  const estimatedTransfer = estimatedAmount * simConfigStore.transfer_fee_rate
  const estimatedFee = estimatedCommission + estimatedStamp + estimatedTransfer

  const baseOrder: SimTradeOrder = {
    order_id: orderId,
    symbol,
    side: payload.side,
    quantity: payload.quantity,
    signal_date: payload.signal_date,
    submit_date: submitDate,
    expected_fill_date: submitDate,
    filled_date: undefined,
    estimated_price: estimatedPrice,
    cash_impact: payload.side === 'buy' ? -(estimatedAmount + estimatedFee) : estimatedAmount - estimatedFee,
    status: 'pending',
  }

  if (payload.quantity % 100 !== 0 || payload.quantity <= 0) {
    baseOrder.status = 'rejected'
    baseOrder.reject_reason = 'SIM_INVALID_LOT_SIZE'
    baseOrder.status_reason = 'SIM_INVALID_LOT_SIZE'
    baseOrder.cash_impact = 0
  } else if (payload.side === 'sell') {
    const available = simLotsStore.filter((lot) => lot.symbol === symbol).reduce((sum, lot) => sum + lot.remaining, 0)
    if (available < payload.quantity) {
      baseOrder.status = 'rejected'
      baseOrder.reject_reason = 'SIM_INSUFFICIENT_POSITION'
      baseOrder.status_reason = 'SIM_INSUFFICIENT_POSITION'
      baseOrder.cash_impact = 0
    }
  } else if (payload.side === 'buy' && simCash < estimatedAmount + estimatedFee) {
    baseOrder.status = 'rejected'
    baseOrder.reject_reason = 'SIM_INSUFFICIENT_CASH'
    baseOrder.status_reason = 'SIM_INSUFFICIENT_CASH'
    baseOrder.cash_impact = 0
  }

  simOrdersStore = [baseOrder, ...simOrdersStore]
  return { order: baseOrder }
}

export function getPortfolio(): PortfolioSnapshot {
  settleOrders()
  const grouped = new Map<string, { quantity: number; cost: number; earliestBuy: string }>()
  simLotsStore.forEach((lot) => {
    const prev = grouped.get(lot.symbol)
    const remainingCost = lot.unit_cost * lot.remaining
    if (!prev) {
      grouped.set(lot.symbol, {
        quantity: lot.remaining,
        cost: remainingCost,
        earliestBuy: lot.buy_date,
      })
      return
    }
    grouped.set(lot.symbol, {
      quantity: prev.quantity + lot.remaining,
      cost: prev.cost + remainingCost,
      earliestBuy: prev.earliestBuy < lot.buy_date ? prev.earliestBuy : lot.buy_date,
    })
  })

  const positions: PortfolioPosition[] = Array.from(grouped.entries()).map(([symbol, item]) => {
    const candles = ensureCandles(symbol)
    const latest = candles[candles.length - 1]
    const currentPrice = latest?.close ?? 0
    const marketValue = currentPrice * item.quantity
    const pnlAmount = marketValue - item.cost
    return {
      symbol,
      name: stockPool.find((row) => row.symbol === symbol)?.name ?? symbol.toUpperCase(),
      quantity: item.quantity,
      available_quantity: item.quantity,
      avg_cost: item.quantity > 0 ? Number((item.cost / item.quantity).toFixed(4)) : 0,
      current_price: Number(currentPrice.toFixed(4)),
      market_value: Number(marketValue.toFixed(4)),
      pnl_amount: Number(pnlAmount.toFixed(4)),
      pnl_ratio: item.cost > 0 ? Number((pnlAmount / item.cost).toFixed(6)) : 0,
      holding_days: Math.max(0, dayjs().diff(dayjs(item.earliestBuy), 'day')),
    }
  })

  const positionValue = positions.reduce((sum, item) => sum + item.market_value, 0)
  const realizedPnl = simClosedTradesStore.reduce((sum, item) => sum + item.pnl_amount, 0)
  const unrealizedPnl = positions.reduce((sum, item) => sum + item.pnl_amount, 0)
  return {
    as_of_date: dayjs().format('YYYY-MM-DD'),
    total_asset: Number((simCash + positionValue).toFixed(4)),
    cash: simCash,
    position_value: Number(positionValue.toFixed(4)),
    realized_pnl: Number(realizedPnl.toFixed(4)),
    unrealized_pnl: Number(unrealizedPnl.toFixed(4)),
    pending_order_count: simOrdersStore.filter((item) => item.status === 'pending').length,
    positions,
  }
}

export function getReview(params?: {
  date_from?: string
  date_to?: string
  date_axis?: 'sell' | 'buy'
}): ReviewResponse {
  settleOrders()
  const now = dayjs()
  const dateFrom = params?.date_from ?? now.subtract(90, 'day').format('YYYY-MM-DD')
  const dateTo = params?.date_to ?? now.format('YYYY-MM-DD')
  const dateAxis = params?.date_axis === 'buy' ? 'buy' : 'sell'
  const resolveAxisDate = (trade: TradeRecord) => (dateAxis === 'buy' ? trade.buy_date : trade.sell_date)
  const trades = simClosedTradesStore.filter((item) => {
    const axisDate = resolveAxisDate(item)
    return axisDate >= dateFrom && axisDate <= dateTo
  })
  const tradeCount = trades.length
  const winCount = trades.filter((row) => row.pnl_amount > 0).length
  const lossCount = trades.filter((row) => row.pnl_amount < 0).length
  const grossProfit = trades.filter((row) => row.pnl_amount > 0).reduce((sum, row) => sum + row.pnl_amount, 0)
  const grossLoss = trades.filter((row) => row.pnl_amount < 0).reduce((sum, row) => sum + row.pnl_amount, 0)
  const totalPnl = trades.reduce((sum, row) => sum + row.pnl_amount, 0)
  const avgPnlRatio = tradeCount > 0 ? trades.reduce((sum, row) => sum + row.pnl_ratio, 0) / tradeCount : 0

  const equityCurve = [{ date: dateFrom, equity: simConfigStore.initial_capital, realized_pnl: 0 }]
  let runningPnl = 0
  trades
    .slice()
    .sort((a, b) => resolveAxisDate(a).localeCompare(resolveAxisDate(b)))
    .forEach((row) => {
      runningPnl += row.pnl_amount
      equityCurve.push({
        date: resolveAxisDate(row),
        equity: Number((simConfigStore.initial_capital + runningPnl).toFixed(4)),
        realized_pnl: Number(runningPnl.toFixed(4)),
      })
    })

  if (equityCurve[equityCurve.length - 1]?.date !== dateTo) {
    equityCurve.push({
      date: dateTo,
      equity: equityCurve[equityCurve.length - 1]?.equity ?? simConfigStore.initial_capital,
      realized_pnl: equityCurve[equityCurve.length - 1]?.realized_pnl ?? 0,
    })
  }

  let peak = equityCurve[0]?.equity ?? simConfigStore.initial_capital
  const drawdownCurve = equityCurve.map((point) => {
    peak = Math.max(peak, point.equity)
    return {
      date: point.date,
      drawdown: peak > 0 ? Number(((point.equity - peak) / peak).toFixed(6)) : 0,
    }
  })

  const monthlyMap = new Map<string, { pnl: number; count: number }>()
  trades.forEach((trade) => {
    const key = resolveAxisDate(trade).slice(0, 7)
    const prev = monthlyMap.get(key) ?? { pnl: 0, count: 0 }
    monthlyMap.set(key, { pnl: prev.pnl + trade.pnl_amount, count: prev.count + 1 })
  })

  const monthlyReturns = Array.from(monthlyMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, value]) => ({
      month,
      return_ratio: Number((value.pnl / simConfigStore.initial_capital).toFixed(6)),
      pnl_amount: Number(value.pnl.toFixed(4)),
      trade_count: value.count,
    }))

  const sortedByPnl = trades.slice().sort((a, b) => b.pnl_amount - a.pnl_amount)
  const topTrades = sortedByPnl.slice(0, 10)
  const bottomTrades = sortedByPnl.slice(-10).reverse()

  const maxDrawdown = Math.max(0, ...drawdownCurve.map((item) => Math.abs(item.drawdown)))
  return {
    stats: {
      win_rate: tradeCount > 0 ? winCount / tradeCount : 0,
      total_return: totalPnl / simConfigStore.initial_capital,
      max_drawdown: maxDrawdown,
      avg_pnl_ratio: avgPnlRatio,
      trade_count: tradeCount,
      win_count: winCount,
      loss_count: lossCount,
      profit_factor: grossLoss < 0 ? grossProfit / Math.abs(grossLoss) : grossProfit > 0 ? 999 : 0,
    },
    trades,
    equity_curve: equityCurve,
    drawdown_curve: drawdownCurve,
    monthly_returns: monthlyReturns,
    top_trades: topTrades,
    bottom_trades: bottomTrades,
    cost_snapshot: simConfigStore,
    range: {
      date_from: dateFrom,
      date_to: dateTo,
      date_axis: dateAxis,
    },
  }
}

export function runBacktestStore(payload: BacktestRunRequest): BacktestResponse {
  let dateFrom = dayjs(payload.date_from)
  let dateTo = dayjs(payload.date_to)
  if (!dateFrom.isValid()) dateFrom = dayjs().subtract(180, 'day')
  if (!dateTo.isValid()) dateTo = dayjs()
  if (dateFrom.isAfter(dateTo)) {
    const swap = dateFrom
    dateFrom = dateTo
    dateTo = swap
  }
  const rangeFrom = dateFrom.format('YYYY-MM-DD')
  const rangeTo = dateTo.format('YYYY-MM-DD')

  const notes: string[] = []
  if (payload.mode === 'trend_pool' && !payload.run_id?.trim()) {
    notes.push('Mock 模式未传 run_id，已按当前信号池模拟趋势池回测。')
  }
  if (payload.priority_topk_per_day > 0 && !payload.prioritize_signals) {
    notes.push('未启用优先排序，priority_topk_per_day 配置未生效。')
  }

  const signalRows = getSignals({
    mode: payload.mode,
    window_days: payload.window_days,
    min_score: payload.min_score,
    require_sequence: payload.require_sequence,
    min_event_count: payload.min_event_count,
  }).items
  const candidatesRaw = signalRows.slice(0, Math.max(0, payload.max_symbols))

  type Candidate = {
    symbol: string
    name: string
    signal_date: string
    entry_date: string
    exit_date: string
    entry_signal: string
    entry_phase: string
    entry_quality_score: number
    entry_phase_score: number
    entry_events_weight: number
    entry_trend_score: number
    entry_structure_score: number
    exit_reason: string
    entry_price: number
    exit_price: number
    holding_days: number
  }

  const candidateRows: Candidate[] = candidatesRaw
    .map((row, index) => {
      const candles = ensureCandles(row.symbol)
      if (candles.length < 10) return null

      const entrySignal = row.wyckoff_signal && payload.entry_events.includes(row.wyckoff_signal)
        ? row.wyckoff_signal
        : payload.entry_events[0] || row.wyckoff_signal || 'Signal'

      let signalDay = dayjs(row.trigger_date)
      if (!signalDay.isValid()) signalDay = dateFrom.add(index % 10, 'day')
      if (signalDay.isBefore(dateFrom)) signalDay = dateFrom
      if (signalDay.isAfter(dateTo)) signalDay = dateTo

      let entryDay = signalDay.add(1, 'day')
      if (entryDay.isBefore(dateFrom)) entryDay = dateFrom
      if (entryDay.isAfter(dateTo)) return null

      const proposedHoldDays = Math.max(2, Math.min(payload.max_hold_days, 3 + (index % 18)))
      let exitDay = entryDay.add(proposedHoldDays, 'day')
      if (exitDay.isAfter(dateTo)) exitDay = dateTo
      if (payload.enforce_t1 && !exitDay.isAfter(entryDay)) {
        const forced = entryDay.add(1, 'day')
        if (forced.isAfter(dateTo)) return null
        exitDay = forced
      }

      const resolvePrice = (targetDate: dayjs.Dayjs) => {
        const target = targetDate.format('YYYY-MM-DD')
        let chosen = candles[0]?.close ?? 20
        for (const candle of candles) {
          if (candle.time <= target) {
            chosen = candle.close
          } else {
            break
          }
        }
        return Math.max(0.01, chosen)
      }

      const entryPrice = resolvePrice(entryDay)
      const quality = row.entry_quality_score ?? 60
      const rawReturn = ((index % 11) - 5) / 100 + (quality - 60) / 500
      const lossCap = payload.stop_loss > 0 ? -payload.stop_loss * 0.95 : -0.12
      const profitCap = payload.take_profit > 0 ? payload.take_profit * 0.95 : 0.2
      const pnlRatio = clamp(rawReturn, lossCap, profitCap)
      const exitPrice = Math.max(0.01, entryPrice * (1 + pnlRatio))

      const pickedExitEvent = payload.exit_events[index % Math.max(1, payload.exit_events.length)] || 'EVENT'
      let exitReason = `event_exit:${pickedExitEvent}`
      if (payload.stop_loss > 0 && pnlRatio <= -payload.stop_loss * 0.9) {
        exitReason = 'stop_loss'
      } else if (payload.take_profit > 0 && pnlRatio >= payload.take_profit * 0.85) {
        exitReason = 'take_profit'
      } else if (index % 3 !== 0) {
        exitReason = index % 2 === 0 ? `event_exit:${pickedExitEvent}` : 'time_exit'
      }

      const phase = row.wyckoff_phase || '阶段未明'
      const entryEventsWeight = (row.wy_events || [])
        .filter((event) => payload.entry_events.includes(event))
        .reduce((sum, event) => sum + ({ PS: 1.0, SC: 1.2, AR: 1.4, ST: 1.6, TSO: 2.5, Spring: 3.0, SOS: 3.4, JOC: 4.0, LPS: 2.8, UTAD: 1.5, SOW: 1.5, LPSY: 1.3 }[event] ?? 1.0), 0)
      const phaseScore = phase.startsWith('吸筹') ? 2.0 : phase.startsWith('派发') ? -1.5 : 0
      const structureScore = String(row.structure_hhh || '-')
        .split('|')
        .reduce((sum, token) => sum + (token && token !== '-' ? 1 : 0), 0)

      return {
        symbol: row.symbol,
        name: row.name,
        signal_date: signalDay.format('YYYY-MM-DD'),
        entry_date: entryDay.format('YYYY-MM-DD'),
        exit_date: exitDay.format('YYYY-MM-DD'),
        entry_signal: entrySignal,
        entry_phase: phase,
        entry_quality_score: quality,
        entry_phase_score: phaseScore,
        entry_events_weight: entryEventsWeight,
        entry_trend_score: row.trend_score ?? 50,
        entry_structure_score: structureScore,
        exit_reason: exitReason,
        entry_price: Number(entryPrice.toFixed(4)),
        exit_price: Number(exitPrice.toFixed(4)),
        holding_days: Math.max(1, exitDay.diff(entryDay, 'day')),
      } satisfies Candidate
    })
    .filter((row): row is Candidate => Boolean(row))

  if (payload.prioritize_signals) {
    candidateRows.sort((a, b) => {
      if (a.entry_date !== b.entry_date) return a.entry_date.localeCompare(b.entry_date)
      if (payload.priority_mode === 'phase_first') {
        if (b.entry_phase_score !== a.entry_phase_score) return b.entry_phase_score - a.entry_phase_score
      } else if (payload.priority_mode === 'momentum') {
        if (b.entry_trend_score !== a.entry_trend_score) return b.entry_trend_score - a.entry_trend_score
      } else if (b.entry_quality_score !== a.entry_quality_score) {
        return b.entry_quality_score - a.entry_quality_score
      }
      if (b.entry_events_weight !== a.entry_events_weight) return b.entry_events_weight - a.entry_events_weight
      return a.symbol.localeCompare(b.symbol)
    })
    notes.push(`同日信号按优先级执行（模式: ${payload.priority_mode}）。`)
  } else {
    candidateRows.sort((a, b) => (a.entry_date === b.entry_date ? a.symbol.localeCompare(b.symbol) : a.entry_date.localeCompare(b.entry_date)))
  }

  if (payload.prioritize_signals && payload.priority_topk_per_day > 0) {
    const beforeCount = candidateRows.length
    const counter = new Map<string, number>()
    const kept = candidateRows.filter((row) => {
      const used = counter.get(row.signal_date) ?? 0
      if (used >= payload.priority_topk_per_day) return false
      counter.set(row.signal_date, used + 1)
      return true
    })
    candidateRows.length = 0
    candidateRows.push(...kept)
    const dropped = beforeCount - kept.length
    if (dropped > 0) {
      notes.push(`同日 TopK 限流已生效：每日保留前 ${payload.priority_topk_per_day} 笔候选，共过滤 ${dropped} 笔。`)
    }
  }

  const feeRate = clamp(payload.fee_bps / 10000, 0, 0.05)
  let cash = payload.initial_capital
  let equity = payload.initial_capital
  let maxConcurrentPositions = 0
  const activePositions: Array<{ exit_date: string; exit_amount: number; pnl_amount: number }> = []
  const trades: BacktestTrade[] = []
  const skipReasons = {
    max_positions: 0,
    insufficient_cash: 0,
    invalid_price: 0,
  }

  const releaseUntil = (entryDate: string) => {
    const remaining: typeof activePositions = []
    activePositions.forEach((row) => {
      if (row.exit_date < entryDate) {
        cash += row.exit_amount
        equity += row.pnl_amount
      } else {
        remaining.push(row)
      }
    })
    activePositions.length = 0
    activePositions.push(...remaining)
  }

  candidateRows.forEach((row) => {
    releaseUntil(row.entry_date)
    if (activePositions.length >= payload.max_positions) {
      skipReasons.max_positions += 1
      return
    }

    const entryExec = row.entry_price * (1 + feeRate)
    const exitExec = row.exit_price * (1 - feeRate)
    if (!Number.isFinite(entryExec) || !Number.isFinite(exitExec) || entryExec <= 0) {
      skipReasons.invalid_price += 1
      return
    }

    const allocation = Math.min(cash, Math.max(0, equity * payload.position_pct))
    const quantity = Math.floor(allocation / entryExec / 100) * 100
    if (quantity <= 0) {
      skipReasons.insufficient_cash += 1
      return
    }

    const invested = quantity * entryExec
    if (invested <= 0 || invested > cash + 1e-9) {
      skipReasons.insufficient_cash += 1
      return
    }

    const exitAmount = quantity * exitExec
    const pnlAmount = exitAmount - invested
    const pnlRatio = invested > 0 ? pnlAmount / invested : 0
    cash -= invested

    activePositions.push({
      exit_date: row.exit_date,
      exit_amount: exitAmount,
      pnl_amount: pnlAmount,
    })
    maxConcurrentPositions = Math.max(maxConcurrentPositions, activePositions.length)

    trades.push({
      symbol: row.symbol,
      name: row.name,
      signal_date: row.signal_date,
      entry_date: row.entry_date,
      exit_date: row.exit_date,
      entry_signal: row.entry_signal,
      entry_phase: row.entry_phase,
      entry_quality_score: Number(row.entry_quality_score.toFixed(2)),
      exit_reason: row.exit_reason,
      quantity,
      entry_price: row.entry_price,
      exit_price: row.exit_price,
      holding_days: row.holding_days,
      pnl_amount: Number(pnlAmount.toFixed(4)),
      pnl_ratio: Number(pnlRatio.toFixed(6)),
    })
  })

  activePositions
    .slice()
    .sort((a, b) => a.exit_date.localeCompare(b.exit_date))
    .forEach((row) => {
      cash += row.exit_amount
      equity += row.pnl_amount
    })

  const candidateCount = candidateRows.length
  const skippedCount = Object.values(skipReasons).reduce((sum, value) => sum + value, 0)
  const fillRate = candidateCount > 0 ? trades.length / candidateCount : 0
  if (skippedCount > 0) {
    const detail = Object.entries(skipReasons)
      .filter(([, value]) => value > 0)
      .map(([key, value]) => `${key}:${value}`)
      .join(', ')
    notes.push(`组合约束跳过 ${skippedCount} 笔信号（${detail}）。`)
  }

  const tradeCount = trades.length
  const winCount = trades.filter((row) => row.pnl_amount > 0).length
  const lossCount = trades.filter((row) => row.pnl_amount < 0).length
  const grossProfit = trades.filter((row) => row.pnl_amount > 0).reduce((sum, row) => sum + row.pnl_amount, 0)
  const grossLoss = trades.filter((row) => row.pnl_amount < 0).reduce((sum, row) => sum + row.pnl_amount, 0)
  const totalPnl = trades.reduce((sum, row) => sum + row.pnl_amount, 0)
  const avgPnlRatio = tradeCount > 0 ? trades.reduce((sum, row) => sum + row.pnl_ratio, 0) / tradeCount : 0

  const pnlByDate = new Map<string, number>()
  trades.forEach((row) => {
    pnlByDate.set(row.exit_date, (pnlByDate.get(row.exit_date) ?? 0) + row.pnl_amount)
  })

  const equityCurve: BacktestResponse['equity_curve'] = [
    {
      date: rangeFrom,
      equity: Number(payload.initial_capital.toFixed(4)),
      realized_pnl: 0,
    },
  ]
  let runningPnl = 0
  Array.from(pnlByDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([date, pnl]) => {
      runningPnl += pnl
      equityCurve.push({
        date,
        equity: Number((payload.initial_capital + runningPnl).toFixed(4)),
        realized_pnl: Number(runningPnl.toFixed(4)),
      })
    })
  if (equityCurve[equityCurve.length - 1]?.date !== rangeTo) {
    equityCurve.push({
      date: rangeTo,
      equity: equityCurve[equityCurve.length - 1]?.equity ?? payload.initial_capital,
      realized_pnl: equityCurve[equityCurve.length - 1]?.realized_pnl ?? runningPnl,
    })
  }

  let peak = equityCurve[0]?.equity ?? payload.initial_capital
  const drawdownCurve = equityCurve.map((point) => {
    peak = Math.max(peak, point.equity)
    return {
      date: point.date,
      drawdown: peak > 0 ? Number(((point.equity - peak) / peak).toFixed(6)) : 0,
    }
  })
  const maxDrawdown = Math.max(0, ...drawdownCurve.map((row) => Math.abs(row.drawdown)))

  const monthlyMap = new Map<string, { pnl: number; count: number }>()
  trades.forEach((row) => {
    const month = row.exit_date.slice(0, 7)
    const prev = monthlyMap.get(month) ?? { pnl: 0, count: 0 }
    monthlyMap.set(month, { pnl: prev.pnl + row.pnl_amount, count: prev.count + 1 })
  })
  const monthlyReturns = Array.from(monthlyMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, value]) => ({
      month,
      return_ratio: payload.initial_capital > 0 ? Number((value.pnl / payload.initial_capital).toFixed(6)) : 0,
      pnl_amount: Number(value.pnl.toFixed(4)),
      trade_count: value.count,
    }))

  const sortedTrades = trades.slice().sort((a, b) => b.pnl_amount - a.pnl_amount)
  const topTrades = sortedTrades.slice(0, 10)
  const bottomTrades = sortedTrades.slice(-10).reverse()

  return {
    stats: {
      win_rate: tradeCount > 0 ? winCount / tradeCount : 0,
      total_return: payload.initial_capital > 0 ? totalPnl / payload.initial_capital : 0,
      max_drawdown: maxDrawdown,
      avg_pnl_ratio: Number(avgPnlRatio.toFixed(6)),
      trade_count: tradeCount,
      win_count: winCount,
      loss_count: lossCount,
      profit_factor: grossLoss < 0 ? Number((grossProfit / Math.abs(grossLoss)).toFixed(6)) : grossProfit > 0 ? 999 : 0,
    },
    trades,
    equity_curve: equityCurve,
    drawdown_curve: drawdownCurve,
    monthly_returns: monthlyReturns,
    top_trades: topTrades,
    bottom_trades: bottomTrades,
    cost_snapshot: {
      initial_capital: payload.initial_capital,
      commission_rate: Number(clamp(payload.fee_bps / 10000, 0, 0.01).toFixed(6)),
      min_commission: 0,
      stamp_tax_rate: 0,
      transfer_fee_rate: 0,
      slippage_rate: 0,
    },
    range: {
      date_from: rangeFrom,
      date_to: rangeTo,
      date_axis: 'sell',
    },
    notes,
    candidate_count: candidateCount,
    skipped_count: skippedCount,
    fill_rate: Number(fillRate.toFixed(6)),
    max_concurrent_positions: maxConcurrentPositions,
  }
}

export function getDailyReviewsStore(params?: { date_from?: string; date_to?: string }): DailyReviewListResponse {
  let rows = dailyReviewsStore.slice()
  if (params?.date_from) rows = rows.filter((row) => row.date >= params.date_from!)
  if (params?.date_to) rows = rows.filter((row) => row.date <= params.date_to!)
  rows.sort((a, b) => b.date.localeCompare(a.date))
  return { items: rows }
}

export function getDailyReviewStore(date: string): DailyReviewRecord | null {
  return dailyReviewsStore.find((row) => row.date === date) ?? null
}

export function upsertDailyReviewStore(date: string, payload: DailyReviewPayload): DailyReviewRecord {
  const record: DailyReviewRecord = {
    ...payload,
    tags: uniqueTokens(payload.tags || []),
    date,
    updated_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  }
  const next = dailyReviewsStore.filter((row) => row.date !== date)
  next.push(record)
  dailyReviewsStore = next.sort((a, b) => b.date.localeCompare(a.date))
  return record
}

export function deleteDailyReviewStore(date: string) {
  const before = dailyReviewsStore.length
  dailyReviewsStore = dailyReviewsStore.filter((row) => row.date !== date)
  return { deleted: dailyReviewsStore.length < before }
}

export function getWeeklyReviewsStore(params?: { year?: number }): WeeklyReviewListResponse {
  let rows = weeklyReviewsStore.slice()
  if (typeof params?.year === 'number') {
    const prefix = `${params.year}-W`
    rows = rows.filter((row) => row.week_label.startsWith(prefix))
  }
  rows.sort((a, b) => b.week_label.localeCompare(a.week_label))
  return { items: rows }
}

export function getWeeklyReviewStore(weekLabel: string): WeeklyReviewRecord | null {
  return weeklyReviewsStore.find((row) => row.week_label === weekLabel) ?? null
}

export function upsertWeeklyReviewStore(weekLabel: string, payload: WeeklyReviewPayload): WeeklyReviewRecord {
  const weekRange = getWeekRangeFromLabel(weekLabel)
  const record: WeeklyReviewRecord = {
    ...payload,
    tags: uniqueTokens(payload.tags || []),
    week_label: weekLabel,
    start_date: payload.start_date || weekRange.start_date,
    end_date: payload.end_date || weekRange.end_date,
    updated_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  }
  const next = weeklyReviewsStore.filter((row) => row.week_label !== weekLabel)
  next.push(record)
  weeklyReviewsStore = next.sort((a, b) => b.week_label.localeCompare(a.week_label))
  return record
}

export function deleteWeeklyReviewStore(weekLabel: string) {
  const before = weeklyReviewsStore.length
  weeklyReviewsStore = weeklyReviewsStore.filter((row) => row.week_label !== weekLabel)
  return { deleted: weeklyReviewsStore.length < before }
}

export function getReviewTagsStore(): ReviewTagsPayload {
  return {
    emotion: reviewTagsStore.emotion.slice(),
    reason: reviewTagsStore.reason.slice(),
  }
}

export function createReviewTagStore(tagType: ReviewTagType, payload: ReviewTagCreateRequest): ReviewTag {
  const name = payload.name.trim()
  const source = reviewTagsStore[tagType]
  const exists = source.find((item) => item.name === name)
  if (exists) return exists
  const palette = ['blue', 'cyan', 'green', 'gold', 'orange', 'red', 'magenta', 'purple', 'geekblue', 'lime']
  const created: ReviewTag = {
    id: `${tagType}-${Date.now().toString(36)}`,
    name,
    color: palette[source.length % palette.length],
    created_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  }
  reviewTagsStore = {
    ...reviewTagsStore,
    [tagType]: [...source, created],
  }
  return created
}

export function deleteReviewTagStore(tagType: ReviewTagType, tagId: string) {
  const before = reviewTagsStore[tagType].length
  reviewTagsStore = {
    ...reviewTagsStore,
    [tagType]: reviewTagsStore[tagType].filter((item) => item.id !== tagId),
  }
  if (tagType === 'emotion') {
    fillTagStore = fillTagStore.map((row) => ({
      ...row,
      emotion_tag_id: row.emotion_tag_id === tagId ? null : row.emotion_tag_id,
    }))
  } else {
    fillTagStore = fillTagStore.map((row) => ({
      ...row,
      reason_tag_ids: row.reason_tag_ids.filter((item) => item !== tagId),
    }))
  }
  fillTagStore = fillTagStore.filter((row) => row.emotion_tag_id || row.reason_tag_ids.length > 0)
  return { deleted: reviewTagsStore[tagType].length < before }
}

export function getReviewFillTagsStore(): TradeFillTagAssignment[] {
  return fillTagStore.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

export function getReviewFillTagStore(orderId: string): TradeFillTagAssignment | null {
  return fillTagStore.find((row) => row.order_id === orderId) ?? null
}

export function updateReviewFillTagStore(orderId: string, payload: TradeFillTagUpdateRequest): TradeFillTagAssignment | null {
  const exists = simFillsStore.some((row) => row.order_id === orderId)
  if (!exists) return null
  const next: TradeFillTagAssignment = {
    order_id: orderId,
    emotion_tag_id: payload.emotion_tag_id ?? null,
    reason_tag_ids: uniqueTokens(payload.reason_tag_ids || []),
    updated_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  }
  fillTagStore = fillTagStore.filter((row) => row.order_id !== orderId)
  if (next.emotion_tag_id || next.reason_tag_ids.length > 0) {
    fillTagStore.unshift(next)
  }
  return next
}

export function getReviewTagStatsStore(params?: { date_from?: string; date_to?: string }): ReviewTagStatsResponse {
  let fills = simFillsStore.slice()
  if (params?.date_from) fills = fills.filter((row) => row.fill_date >= params.date_from!)
  if (params?.date_to) fills = fills.filter((row) => row.fill_date <= params.date_to!)

  const fillMap = new Map<string, SimTradeFill>()
  fills.forEach((row) => fillMap.set(row.order_id, row))

  const emotionRows = reviewTagsStore.emotion.map((tag) => ({
    tag_id: tag.id,
    name: tag.name,
    color: tag.color,
    count: 0,
    gross_amount: 0,
    net_amount: 0,
  }))
  const reasonRows = reviewTagsStore.reason.map((tag) => ({
    tag_id: tag.id,
    name: tag.name,
    color: tag.color,
    count: 0,
    gross_amount: 0,
    net_amount: 0,
  }))

  const emotionIndex = new Map(emotionRows.map((row) => [row.tag_id, row]))
  const reasonIndex = new Map(reasonRows.map((row) => [row.tag_id, row]))

  fillTagStore.forEach((assignment) => {
    const fill = fillMap.get(assignment.order_id)
    if (!fill) return
    if (assignment.emotion_tag_id && emotionIndex.has(assignment.emotion_tag_id)) {
      const row = emotionIndex.get(assignment.emotion_tag_id)!
      row.count += 1
      row.gross_amount += fill.gross_amount
      row.net_amount += fill.net_amount
    }
    assignment.reason_tag_ids.forEach((tagId) => {
      if (!reasonIndex.has(tagId)) return
      const row = reasonIndex.get(tagId)!
      row.count += 1
      row.gross_amount += fill.gross_amount
      row.net_amount += fill.net_amount
    })
  })

  return {
    date_from: params?.date_from,
    date_to: params?.date_to,
    emotion: emotionRows.filter((row) => row.count > 0).sort((a, b) => b.count - a.count),
    reason: reasonRows.filter((row) => row.count > 0).sort((a, b) => b.count - a.count),
  }
}

export function getMarketNewsStore(params?: {
  query?: string
  symbol?: string
  source_domains?: string[]
  age_hours?: 24 | 48 | 72
  refresh?: boolean
  limit?: number
}): MarketNewsResponse {
  const normalizedQuery = (params?.query || 'A股 热点').trim()
  const normalizedSymbol = (params?.symbol || '').trim().toLowerCase()
  const selectedDomains = [...new Set((params?.source_domains || []).map((item) => item.trim().toLowerCase()).filter(Boolean))]
  const ageHours = params?.age_hours && [24, 48, 72].includes(params.age_hours) ? params.age_hours : 72
  const defaultQueryTokens = new Set(['a股', '热点', 'a股热点', 'a股 热点'])
  const normalizedCompact = normalizedQuery.replace(/\s+/g, '').toLowerCase()
  const queryTokens = defaultQueryTokens.has(normalizedCompact)
    ? []
    : normalizedQuery.toLowerCase().split(/\s+/).filter(Boolean)
  const tokens = [...queryTokens, normalizedSymbol].filter(Boolean)
  const limit = Math.min(Math.max(params?.limit ?? 20, 1), 50)
  const cacheKey = `${normalizedQuery}|${normalizedSymbol}|${selectedDomains.join(',')}|${ageHours}|${limit}`
  const nowTs = Date.now()
  const cached = marketNewsCacheStore.get(cacheKey)
  if (!params?.refresh && cached && nowTs - cached.ts <= 180_000) {
    return {
      query: normalizedQuery || 'A股 热点',
      age_hours: ageHours,
      symbol: normalizedSymbol || undefined,
      symbol_name: normalizedSymbol ? normalizedSymbol.toUpperCase() : undefined,
      source_domains: selectedDomains,
      items: cached.items.slice(0, limit),
      fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      cache_hit: true,
      fallback_used: false,
      degraded: false,
      degraded_reason: undefined,
    }
  }

  let rows = marketNewsSeed.slice()
  rows = rows.filter((item) => dayjs(item.pub_date).isAfter(dayjs().subtract(ageHours, 'hour')))
  if (tokens.length > 0) {
    rows = rows.filter((item) => {
      const corpus = `${item.title} ${item.snippet} ${item.source_name}`.toLowerCase()
      return tokens.some((token) => corpus.includes(token))
    })
  }
  if (selectedDomains.length > 0) {
    rows = rows.filter((item) => {
      try {
        const host = new URL(item.url).host.toLowerCase().replace(/^www\./, '')
        return selectedDomains.some((domain) => host === domain || host.endsWith(`.${domain}`))
      } catch {
        return false
      }
    })
  }

  const items = rows.slice(0, limit)
  if (items.length > 0) {
    marketNewsLastSuccess = items
    marketNewsCacheStore.set(cacheKey, { ts: nowTs, items })
    return {
      query: normalizedQuery || 'A股 热点',
      age_hours: ageHours,
      symbol: normalizedSymbol || undefined,
      symbol_name: normalizedSymbol ? normalizedSymbol.toUpperCase() : undefined,
      source_domains: selectedDomains,
      items,
      fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      cache_hit: false,
      fallback_used: false,
      degraded: false,
      degraded_reason: undefined,
    }
  }

  if (marketNewsLastSuccess.length > 0) {
    return {
      query: normalizedQuery || 'A股 热点',
      age_hours: ageHours,
      symbol: normalizedSymbol || undefined,
      symbol_name: normalizedSymbol ? normalizedSymbol.toUpperCase() : undefined,
      source_domains: selectedDomains,
      items: marketNewsLastSuccess.slice(0, limit),
      fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
      cache_hit: false,
      fallback_used: true,
      degraded: true,
      degraded_reason: 'MOCK_NEWS_FALLBACK_CACHE',
    }
  }

  return {
    query: normalizedQuery || 'A股 热点',
    age_hours: ageHours,
    symbol: normalizedSymbol || undefined,
    symbol_name: normalizedSymbol ? normalizedSymbol.toUpperCase() : undefined,
    source_domains: selectedDomains,
    items: [],
    fetched_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    cache_hit: false,
    fallback_used: false,
    degraded: true,
    degraded_reason: 'MOCK_NEWS_EMPTY',
  }
}

export function getOrders(params?: {
  status?: 'pending' | 'filled' | 'cancelled' | 'rejected'
  symbol?: string
  side?: 'buy' | 'sell'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}): SimOrdersResponse {
  const page = params?.page ?? 1
  const pageSize = params?.page_size ?? 50
  let rows = simOrdersStore.slice()
  if (params?.status) rows = rows.filter((row) => row.status === params.status)
  if (params?.symbol) rows = rows.filter((row) => row.symbol === params.symbol?.trim().toLowerCase())
  if (params?.side) rows = rows.filter((row) => row.side === params.side)
  if (params?.date_from) rows = rows.filter((row) => row.submit_date >= params.date_from!)
  if (params?.date_to) rows = rows.filter((row) => row.submit_date <= params.date_to!)
  const total = rows.length
  const start = Math.max(0, (page - 1) * pageSize)
  return {
    items: rows.slice(start, start + pageSize),
    total,
    page,
    page_size: pageSize,
  }
}

export function getFills(params?: {
  symbol?: string
  side?: 'buy' | 'sell'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}): SimFillsResponse {
  const page = params?.page ?? 1
  const pageSize = params?.page_size ?? 50
  let rows = simFillsStore.slice()
  if (params?.symbol) rows = rows.filter((row) => row.symbol === params.symbol?.trim().toLowerCase())
  if (params?.side) rows = rows.filter((row) => row.side === params.side)
  if (params?.date_from) rows = rows.filter((row) => row.fill_date >= params.date_from!)
  if (params?.date_to) rows = rows.filter((row) => row.fill_date <= params.date_to!)
  const total = rows.length
  const start = Math.max(0, (page - 1) * pageSize)
  return {
    items: rows.slice(start, start + pageSize),
    total,
    page,
    page_size: pageSize,
  }
}

export function cancelOrder(orderId: string) {
  const index = simOrdersStore.findIndex((item) => item.order_id === orderId)
  if (index < 0) {
    return null
  }
  const target = simOrdersStore[index]
  if (target.status !== 'pending') {
    return { order: target, fill: undefined }
  }
  simOrdersStore[index] = {
    ...target,
    status: 'cancelled',
    status_reason: 'USER_CANCELLED',
  }
  return { order: simOrdersStore[index], fill: undefined }
}

export function settleOrders(): SimSettleResponse {
  let settledCount = 0
  let filledCount = 0
  simOrdersStore.forEach((order) => {
    if (order.status !== 'pending') return
    settledCount += 1
    const fill = applyOrderFill(order)
    if (fill) filledCount += 1
  })
  return {
    settled_count: settledCount,
    filled_count: filledCount,
    pending_count: simOrdersStore.filter((item) => item.status === 'pending').length,
    as_of_date: dayjs().format('YYYY-MM-DD'),
    last_settle_at: dayjs().format('YYYY-MM-DD HH:mm:ss'),
  }
}

export function resetAccount(): SimResetResponse {
  simOrdersStore = []
  simFillsStore = []
  simLotsStore = []
  simClosedTradesStore = []
  simCash = simConfigStore.initial_capital
  return {
    success: true,
    as_of_date: dayjs().format('YYYY-MM-DD'),
    cash: simCash,
  }
}

export function getSimConfigStore() {
  return simConfigStore
}

export function setSimConfigStore(payload: SimTradingConfig) {
  simConfigStore = payload
  if (simOrdersStore.length === 0 && simFillsStore.length === 0 && simLotsStore.length === 0) {
    simCash = payload.initial_capital
  }
  return simConfigStore
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

export function getSystemStorageStore(): SystemStorageStatus {
  const configured = configStore.akshare_cache_dir || ''
  const normalized = configured.replace(/%USERPROFILE%/gi, 'C:\\Users\\demo')
  const resolved = normalized || 'C:\\Users\\demo\\.tdx-trend\\akshare\\daily'
  return {
    app_state_path: 'C:\\Users\\demo\\.tdx-trend\\app_state.json',
    app_state_exists: true,
    sim_state_path: 'C:\\Users\\demo\\.tdx-trend\\sim_state.json',
    sim_state_exists: true,
    akshare_cache_dir: configured,
    akshare_cache_dir_resolved: resolved,
    akshare_cache_dir_exists: true,
    akshare_cache_file_count: 12,
    akshare_cache_candidates: [
      resolved,
      'C:\\Users\\demo\\.tdx-trend\\akshare\\daily',
      'D:\\data\\akshare\\daily',
    ],
  }
}

export function syncMarketDataStore(payload: MarketDataSyncRequest): MarketDataSyncResponse {
  const provider = payload.provider || 'baostock'
  const mode = payload.mode || 'incremental'
  const symbolCount = payload.all_market ? Math.min(Math.max(payload.limit || 300, 1), 3000) : 8
  const okCount = Math.max(1, Math.floor(symbolCount * 0.98))
  const failCount = Math.max(0, symbolCount - okCount)
  const skippedCount = mode === 'incremental' ? Math.floor(symbolCount * 0.7) : 0
  const newRowsTotal = mode === 'incremental' ? Math.max(1, Math.floor(symbolCount * 1.2)) : symbolCount * 180
  const now = dayjs().format('YYYY-MM-DD HH:mm:ss')
  const outDir = payload.out_dir?.trim() || configStore.akshare_cache_dir
  return {
    ok: failCount === 0,
    provider,
    mode,
    message: `Mock ${provider} 同步完成：成功 ${okCount}，失败 ${failCount}，跳过 ${skippedCount}，新增 ${newRowsTotal} 行`,
    out_dir: outDir,
    symbol_count: symbolCount,
    ok_count: okCount,
    fail_count: failCount,
    skipped_count: skippedCount,
    new_rows_total: newRowsTotal,
    started_at: now,
    finished_at: now,
    duration_sec: 0.8,
    errors: failCount > 0 ? ['mock: 网络波动导致少量失败'] : [],
  }
}
