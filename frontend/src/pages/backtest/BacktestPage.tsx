import { useEffect, useMemo, useState } from 'react'
import dayjs, { Dayjs } from 'dayjs'
import { useMutation } from '@tanstack/react-query'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  DatePicker,
  Input,
  InputNumber,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import ReactECharts from 'echarts-for-react'
import { Link } from 'react-router-dom'
import { ApiError } from '@/shared/api/client'
import {
  cancelBacktestTask,
  pauseBacktestTask,
  runBacktestPlateau,
  resumeBacktestTask,
  startBacktestTask,
} from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import { useBacktestTaskStore } from '@/state/backtestTaskStore'
import type {
  BacktestPlateauPoint,
  BacktestPlateauResponse,
  BacktestPoolRollMode,
  BacktestPriorityMode,
  BacktestTaskStatusResponse,
  BacktestTrade,
  BoardFilter,
  SignalScanMode,
  TrendPoolStep,
} from '@/types/contracts'
import { formatMoney, formatPct } from '@/shared/utils/format'

const TRADE_BACKTEST_DEFAULTS = {
  mode: 'trend_pool' as SignalScanMode,
  trendStep: 'auto' as TrendPoolStep,
  poolRollMode: 'daily' as BacktestPoolRollMode,
  windowDays: 60,
  minScore: 55,
  minEventCount: 1,
  requireSequence: false,
  entryEvents: ['Spring', 'SOS', 'JOC', 'LPS'],
  exitEvents: ['UTAD', 'SOW', 'LPSY'],
  initialCapital: 1_000_000,
  positionPct: 0.2,
  maxPositions: 5,
  stopLoss: 0.05,
  takeProfit: 0.15,
  maxHoldDays: 60,
  feeBps: 10,
  prioritizeSignals: true,
  priorityMode: 'balanced' as BacktestPriorityMode,
  priorityTopK: 0,
  enforceT1: true,
  maxSymbols: 120,
  defaultLookbackDays: 180,
}

const SCREENER_CACHE_KEY = 'tdx-trend-screener-cache-v4'
const BACKTEST_FORM_CACHE_KEY = 'tdx-trend-backtest-form-v2'
const BACKTEST_PLATEAU_PRESETS_KEY = 'tdx-trend-backtest-plateau-presets-v1'
const WY_EVENTS = ['PS', 'SC', 'AR', 'ST', 'TSO', 'Spring', 'SOS', 'JOC', 'LPS', 'UTAD', 'SOW', 'LPSY']
const BACKTEST_DEFAULT_BOARD_FILTERS: BoardFilter[] = ['main', 'gem', 'star']
const ALLOWED_BOARD_FILTERS: BoardFilter[] = ['main', 'gem', 'star', 'beijing', 'st']
type BacktestPlateauTableRow = BacktestPlateauPoint & { __rowKey: string; __rank: number }
type BacktestPlateauPreset = { id: string; name: string; saved_at: string; point: BacktestPlateauPoint }
type PlateauAxisKey =
  | 'window_days'
  | 'min_score'
  | 'stop_loss'
  | 'take_profit'
  | 'max_positions'
  | 'position_pct'
  | 'max_symbols'
  | 'priority_topk_per_day'
type PlateauMetricKey = 'score' | 'total_return'

const PLATEAU_AXIS_OPTIONS: Array<{ value: PlateauAxisKey; label: string }> = [
  { value: 'window_days', label: '信号窗口天数' },
  { value: 'min_score', label: '最低评分' },
  { value: 'stop_loss', label: '止损比例(%)' },
  { value: 'take_profit', label: '止盈比例(%)' },
  { value: 'max_positions', label: '最大并发持仓' },
  { value: 'position_pct', label: '单笔仓位占比(%)' },
  { value: 'max_symbols', label: '最大股票数' },
  { value: 'priority_topk_per_day', label: '同日TopK' },
]

const PLATEAU_METRIC_OPTIONS: Array<{ value: PlateauMetricKey; label: string }> = [
  { value: 'score', label: '评分' },
  { value: 'total_return', label: '总收益率' },
]

const PLATEAU_AXIS_LABEL_MAP: Record<PlateauAxisKey, string> = Object.fromEntries(
  PLATEAU_AXIS_OPTIONS.map((item) => [item.value, item.label]),
) as Record<PlateauAxisKey, string>

const PLATEAU_METRIC_LABEL_MAP: Record<PlateauMetricKey, string> = Object.fromEntries(
  PLATEAU_METRIC_OPTIONS.map((item) => [item.value, item.label]),
) as Record<PlateauMetricKey, string>

type BacktestFormDraft = {
  mode: SignalScanMode
  trend_step: TrendPoolStep
  pool_roll_mode: BacktestPoolRollMode
  run_id: string
  board_filters: BoardFilter[]
  date_from: string
  date_to: string
  window_days: number
  min_score: number
  require_sequence: boolean
  min_event_count: number
  entry_events: string[]
  exit_events: string[]
  initial_capital: number
  position_pct: number
  max_positions: number
  stop_loss: number
  take_profit: number
  max_hold_days: number
  fee_bps: number
  prioritize_signals: boolean
  priority_mode: BacktestPriorityMode
  priority_topk_per_day: number
  enforce_t1: boolean
  max_symbols: number
  trades_page_size: number
}

function formatApiError(error: unknown) {
  if (error instanceof ApiError) return error.message || `请求失败: ${error.code}`
  if (error instanceof Error) return error.message || '请求失败'
  return '请求失败'
}

function toPercent(value: number) {
  return Number((value * 100).toFixed(2))
}

function toRatio(percentValue: number, fallback: number, lower: number, upper: number) {
  const raw = Number.isFinite(percentValue) ? percentValue / 100 : fallback
  return Math.max(lower, Math.min(upper, Number(raw.toFixed(6))))
}

function parseNumericList(
  raw: string,
  options: {
    integer?: boolean
    min: number
    max: number
    precision?: number
    maxLength?: number
  },
): number[] {
  const {
    integer = false,
    min,
    max,
    precision = 6,
    maxLength = 16,
  } = options
  const tokens = String(raw || '')
    .split(/[,\s，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  if (tokens.length === 0) return []
  const result: number[] = []
  const seen = new Set<string>()
  for (const token of tokens) {
    if (result.length >= maxLength) break
    const parsed = Number(token)
    if (!Number.isFinite(parsed)) continue
    let value = Math.max(min, Math.min(max, parsed))
    if (integer) {
      value = Math.round(value)
    } else {
      value = Number(value.toFixed(precision))
    }
    const key = integer ? String(Math.round(value)) : value.toFixed(precision)
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}

function buildPlateauRowKey(row: BacktestPlateauPoint, index: number) {
  const params = row.params
  return [
    params.window_days,
    Number(params.min_score).toFixed(4),
    Number(params.stop_loss).toFixed(6),
    Number(params.take_profit).toFixed(6),
    params.max_positions,
    Number(params.position_pct).toFixed(6),
    params.max_symbols,
    params.priority_topk_per_day,
    index,
  ].join('|')
}

function buildPlateauParamsKey(point: BacktestPlateauPoint): string {
  const params = point.params
  return [
    params.window_days,
    Number(params.min_score).toFixed(4),
    Number(params.stop_loss).toFixed(6),
    Number(params.take_profit).toFixed(6),
    params.max_positions,
    Number(params.position_pct).toFixed(6),
    params.max_symbols,
    params.priority_topk_per_day,
  ].join('|')
}

function getPlateauAxisRawValue(point: BacktestPlateauPoint, axis: PlateauAxisKey): number {
  if (axis === 'window_days') return Number(point.params.window_days)
  if (axis === 'min_score') return Number(point.params.min_score)
  if (axis === 'stop_loss') return Number(point.params.stop_loss) * 100
  if (axis === 'take_profit') return Number(point.params.take_profit) * 100
  if (axis === 'max_positions') return Number(point.params.max_positions)
  if (axis === 'position_pct') return Number(point.params.position_pct) * 100
  if (axis === 'max_symbols') return Number(point.params.max_symbols)
  return Number(point.params.priority_topk_per_day)
}

function formatPlateauAxisCategory(axis: PlateauAxisKey, value: number): string {
  if (axis === 'window_days' || axis === 'max_positions' || axis === 'max_symbols' || axis === 'priority_topk_per_day') {
    return String(Math.round(value))
  }
  if (axis === 'min_score') return Number(value).toFixed(2)
  return `${Number(value).toFixed(2)}%`
}

function getPlateauMetricValue(point: BacktestPlateauPoint, metric: PlateauMetricKey): number {
  if (metric === 'score') return Number(point.score)
  return Number(point.stats.total_return)
}

function formatPlateauMetricValue(metric: PlateauMetricKey, value: number): string {
  if (metric === 'score') return Number(value).toFixed(3)
  return formatPct(Number(value))
}

function buildPlateauCellKey(xValue: number, yValue: number): string {
  return `${Number(xValue).toFixed(6)}|${Number(yValue).toFixed(6)}`
}

function sanitizeBoardFilters(raw: unknown): BoardFilter[] {
  if (!Array.isArray(raw)) return []
  const selected = raw
    .map((item) => String(item).trim())
    .filter((item): item is BoardFilter => ALLOWED_BOARD_FILTERS.includes(item as BoardFilter))
  return Array.from(new Set(selected))
}

function buildDefaultDraft(): BacktestFormDraft {
  const dateTo = dayjs().subtract(1, 'day').format('YYYY-MM-DD')
  const dateFrom = dayjs(dateTo).subtract(TRADE_BACKTEST_DEFAULTS.defaultLookbackDays, 'day').format('YYYY-MM-DD')
  return {
    mode: TRADE_BACKTEST_DEFAULTS.mode,
    trend_step: TRADE_BACKTEST_DEFAULTS.trendStep,
    pool_roll_mode: TRADE_BACKTEST_DEFAULTS.poolRollMode,
    run_id: '',
    board_filters: BACKTEST_DEFAULT_BOARD_FILTERS,
    date_from: dateFrom,
    date_to: dateTo,
    window_days: TRADE_BACKTEST_DEFAULTS.windowDays,
    min_score: TRADE_BACKTEST_DEFAULTS.minScore,
    require_sequence: TRADE_BACKTEST_DEFAULTS.requireSequence,
    min_event_count: TRADE_BACKTEST_DEFAULTS.minEventCount,
    entry_events: TRADE_BACKTEST_DEFAULTS.entryEvents,
    exit_events: TRADE_BACKTEST_DEFAULTS.exitEvents,
    initial_capital: TRADE_BACKTEST_DEFAULTS.initialCapital,
    position_pct: TRADE_BACKTEST_DEFAULTS.positionPct,
    max_positions: TRADE_BACKTEST_DEFAULTS.maxPositions,
    stop_loss: TRADE_BACKTEST_DEFAULTS.stopLoss,
    take_profit: TRADE_BACKTEST_DEFAULTS.takeProfit,
    max_hold_days: TRADE_BACKTEST_DEFAULTS.maxHoldDays,
    fee_bps: TRADE_BACKTEST_DEFAULTS.feeBps,
    prioritize_signals: TRADE_BACKTEST_DEFAULTS.prioritizeSignals,
    priority_mode: TRADE_BACKTEST_DEFAULTS.priorityMode,
    priority_topk_per_day: TRADE_BACKTEST_DEFAULTS.priorityTopK,
    enforce_t1: TRADE_BACKTEST_DEFAULTS.enforceT1,
    max_symbols: TRADE_BACKTEST_DEFAULTS.maxSymbols,
    trades_page_size: 25,
  }
}

function loadBacktestDraft(): BacktestFormDraft {
  const defaults = buildDefaultDraft()
  if (typeof window === 'undefined') return defaults
  try {
    const raw = window.localStorage.getItem(BACKTEST_FORM_CACHE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<BacktestFormDraft>
    const merged = { ...defaults, ...parsed }
    if (!dayjs(merged.date_from).isValid()) merged.date_from = defaults.date_from
    if (!dayjs(merged.date_to).isValid()) merged.date_to = defaults.date_to
    if (!Array.isArray(merged.entry_events) || merged.entry_events.length === 0) {
      merged.entry_events = defaults.entry_events
    }
    if (!Array.isArray(merged.exit_events) || merged.exit_events.length === 0) {
      merged.exit_events = defaults.exit_events
    }
    const boardFilters = sanitizeBoardFilters(merged.board_filters)
    merged.board_filters = boardFilters.length > 0 ? boardFilters : defaults.board_filters
    if (!['daily', 'weekly', 'position'].includes(String(merged.pool_roll_mode))) {
      merged.pool_roll_mode = defaults.pool_roll_mode
    }
    if (!Number.isFinite(merged.trades_page_size) || (merged.trades_page_size ?? 0) <= 0) {
      merged.trades_page_size = defaults.trades_page_size
    }
    return merged
  } catch {
    return defaults
  }
}

function persistBacktestDraft(draft: BacktestFormDraft) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(BACKTEST_FORM_CACHE_KEY, JSON.stringify(draft))
  } catch {
    // ignore local storage errors
  }
}

function loadBacktestPlateauPresets(): BacktestPlateauPreset[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(BACKTEST_PLATEAU_PRESETS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    const out: BacktestPlateauPreset[] = []
    for (const item of parsed) {
      const row = item as Partial<BacktestPlateauPreset>
      const id = String(row?.id || '').trim()
      const name = String(row?.name || '').trim()
      const savedAt = String(row?.saved_at || '').trim()
      const point = row?.point as BacktestPlateauPoint | undefined
      if (!id || !name || !savedAt || !point || !point.params || !point.stats) continue
      out.push({
        id,
        name,
        saved_at: savedAt,
        point,
      })
    }
    return out.slice(0, 300)
  } catch {
    return []
  }
}

function persistBacktestPlateauPresets(presets: BacktestPlateauPreset[]) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      BACKTEST_PLATEAU_PRESETS_KEY,
      JSON.stringify(presets.slice(0, 300)),
    )
  } catch {
    // ignore local storage errors
  }
}

type ExitReasonView = {
  label: string
  color?: string
  detail?: string
}

function parseExitReason(value: string): ExitReasonView {
  const text = String(value || '').trim()
  if (text.startsWith('event_exit')) {
    const detail = text.includes(':') ? text.split(':').slice(1).join(':').trim() : ''
    return { label: '事件', color: 'blue', detail: detail || undefined }
  }
  if (text === 'stop_loss') return { label: '止损', color: 'red' }
  if (text === 'take_profit') return { label: '止盈', color: 'green' }
  if (text === 'time_exit') return { label: '超时', color: 'gold' }
  if (text === 'eod_exit') return { label: '收盘', color: 'purple' }
  if (!text) return { label: '未知' }
  return { label: text }
}

function buildChartPath(symbol: string, name?: string) {
  const symbolText = String(symbol || '').trim()
  if (!symbolText) return ''
  const params = new URLSearchParams()
  const nameText = String(name || '').trim()
  if (nameText) params.set('signal_stock_name', nameText)
  const query = params.toString()
  return `/stocks/${symbolText}/chart${query ? `?${query}` : ''}`
}

function taskStatusLabel(status: BacktestTaskStatusResponse['status']) {
  if (status === 'pending') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'paused') return '已暂停'
  if (status === 'succeeded') return '已完成'
  if (status === 'cancelled') return '已停止'
  return '失败'
}

function taskStatusColor(status: BacktestTaskStatusResponse['status']) {
  if (status === 'pending') return 'default'
  if (status === 'running') return 'processing'
  if (status === 'paused') return 'warning'
  if (status === 'succeeded') return 'success'
  if (status === 'cancelled') return 'default'
  return 'error'
}

const tradeColumns: ColumnsType<BacktestTrade> = [
  {
    title: '代码',
    dataIndex: 'symbol',
    width: 110,
    render: (value: string, row) => {
      const symbol = String(value || '').trim()
      if (!symbol) return '--'
      const target = buildChartPath(symbol, row.name)
      return <Link to={target}>{symbol}</Link>
    },
  },
  {
    title: '名称',
    dataIndex: 'name',
    width: 120,
    render: (value: string, row) => {
      const symbol = String(row.symbol || '').trim()
      const name = String(value || '').trim()
      if (!symbol) return name || '--'
      const target = buildChartPath(symbol, name || row.name)
      return <Link to={target}>{name || '--'}</Link>
    },
  },
  { title: '信号日', dataIndex: 'signal_date', width: 110 },
  { title: '买入日', dataIndex: 'entry_date', width: 110 },
  { title: '卖出日', dataIndex: 'exit_date', width: 110 },
  { title: '入场事件', dataIndex: 'entry_signal', width: 130 },
  {
    title: '质量分',
    dataIndex: 'entry_quality_score',
    width: 88,
    render: (value: number) => value.toFixed(1),
  },
  {
    title: '离场事件/原因',
    dataIndex: 'exit_reason',
    width: 180,
    render: (value: string) => {
      const parsed = parseExitReason(value)
      if (parsed.detail) {
        return (
          <Space size={6}>
            <Tag color={parsed.color}>{parsed.label}</Tag>
            <span>{parsed.detail}</span>
          </Space>
        )
      }
      return <Tag color={parsed.color}>{parsed.label}</Tag>
    },
  },
  { title: '数量', dataIndex: 'quantity', width: 92 },
  { title: '买入价', dataIndex: 'entry_price', width: 90 },
  { title: '卖出价', dataIndex: 'exit_price', width: 90 },
  { title: '持仓天数', dataIndex: 'holding_days', width: 92 },
  {
    title: '盈亏额',
    dataIndex: 'pnl_amount',
    width: 124,
    render: (value: number) => <span style={{ color: value >= 0 ? '#c4473d' : '#19744f' }}>{formatMoney(value)}</span>,
  },
  {
    title: '盈亏比',
    dataIndex: 'pnl_ratio',
    width: 96,
    render: (value: number) => formatPct(value),
  },
]

const plateauColumns: ColumnsType<BacktestPlateauTableRow> = [
  {
    title: '评分',
    dataIndex: 'score',
    width: 90,
    render: (value: number) => value.toFixed(3),
  },
  {
    title: '总收益',
    dataIndex: ['stats', 'total_return'],
    width: 90,
    render: (value: number) => formatPct(value),
  },
  {
    title: '最大回撤',
    dataIndex: ['stats', 'max_drawdown'],
    width: 100,
    render: (value: number) => formatPct(value),
  },
  {
    title: '胜率',
    dataIndex: ['stats', 'win_rate'],
    width: 90,
    render: (value: number) => formatPct(value),
  },
  { title: '交易数', dataIndex: ['stats', 'trade_count'], width: 80 },
  { title: '窗口', dataIndex: ['params', 'window_days'], width: 70 },
  { title: '最低分', dataIndex: ['params', 'min_score'], width: 80 },
  {
    title: '止损%',
    dataIndex: ['params', 'stop_loss'],
    width: 80,
    render: (value: number) => `${(Number(value) * 100).toFixed(2)}%`,
  },
  {
    title: '止盈%',
    dataIndex: ['params', 'take_profit'],
    width: 80,
    render: (value: number) => `${(Number(value) * 100).toFixed(2)}%`,
  },
  { title: '仓位上限', dataIndex: ['params', 'max_positions'], width: 86 },
  {
    title: '单笔%',
    dataIndex: ['params', 'position_pct'],
    width: 78,
    render: (value: number) => `${(Number(value) * 100).toFixed(1)}%`,
  },
  { title: '股票数', dataIndex: ['params', 'max_symbols'], width: 78 },
  { title: 'TopK', dataIndex: ['params', 'priority_topk_per_day'], width: 70 },
  {
    title: '状态',
    dataIndex: 'error',
    width: 90,
    render: (value: string | null | undefined, row) => {
      if (value) return <Tag color="error">失败</Tag>
      if (row.cache_hit) return <Tag color="processing">缓存</Tag>
      return <Tag color="success">成功</Tag>
    },
  },
]

export function BacktestPage() {
  const { message } = AntdApp.useApp()
  const initialDraft = useMemo(() => loadBacktestDraft(), [])

  const [mode, setMode] = useState<SignalScanMode>(initialDraft.mode)
  const [trendStep, setTrendStep] = useState<TrendPoolStep>(initialDraft.trend_step)
  const [poolRollMode, setPoolRollMode] = useState<BacktestPoolRollMode>(initialDraft.pool_roll_mode)
  const [runId, setRunId] = useState(initialDraft.run_id)
  const [boardFilters, setBoardFilters] = useState<BoardFilter[]>(initialDraft.board_filters)
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs(initialDraft.date_from),
    dayjs(initialDraft.date_to),
  ])
  const [entryEvents, setEntryEvents] = useState<string[]>(initialDraft.entry_events)
  const [exitEvents, setExitEvents] = useState<string[]>(initialDraft.exit_events)
  const [initialCapital, setInitialCapital] = useState(initialDraft.initial_capital)
  const [positionPctPercent, setPositionPctPercent] = useState(toPercent(initialDraft.position_pct))
  const [maxPositions, setMaxPositions] = useState(initialDraft.max_positions)
  const [stopLossPercent, setStopLossPercent] = useState(toPercent(initialDraft.stop_loss))
  const [takeProfitPercent, setTakeProfitPercent] = useState(toPercent(initialDraft.take_profit))
  const [maxHoldDays, setMaxHoldDays] = useState(initialDraft.max_hold_days)
  const [feeBps, setFeeBps] = useState(initialDraft.fee_bps)
  const [windowDays, setWindowDays] = useState(initialDraft.window_days)
  const [minScore, setMinScore] = useState(initialDraft.min_score)
  const [minEventCount, setMinEventCount] = useState(initialDraft.min_event_count)
  const [requireSequence, setRequireSequence] = useState(initialDraft.require_sequence)
  const [prioritizeSignals, setPrioritizeSignals] = useState(initialDraft.prioritize_signals)
  const [priorityMode, setPriorityMode] = useState<BacktestPriorityMode>(initialDraft.priority_mode)
  const [priorityTopK, setPriorityTopK] = useState(initialDraft.priority_topk_per_day)
  const [enforceT1, setEnforceT1] = useState(initialDraft.enforce_t1)
  const [maxSymbols, setMaxSymbols] = useState(initialDraft.max_symbols)
  const [plateauSamplingMode, setPlateauSamplingMode] = useState<'grid' | 'lhs'>('lhs')
  const [plateauSamplePoints, setPlateauSamplePoints] = useState(120)
  const [plateauRandomSeed, setPlateauRandomSeed] = useState<number | null>(20260221)
  const [plateauWindowListRaw, setPlateauWindowListRaw] = useState('')
  const [plateauMinScoreListRaw, setPlateauMinScoreListRaw] = useState('')
  const [plateauStopLossPctListRaw, setPlateauStopLossPctListRaw] = useState('')
  const [plateauTakeProfitPctListRaw, setPlateauTakeProfitPctListRaw] = useState('')
  const [plateauMaxPositionsListRaw, setPlateauMaxPositionsListRaw] = useState('')
  const [plateauPositionPctListRaw, setPlateauPositionPctListRaw] = useState('')
  const [plateauMaxSymbolsListRaw, setPlateauMaxSymbolsListRaw] = useState('')
  const [plateauTopKListRaw, setPlateauTopKListRaw] = useState('')
  const [plateauResult, setPlateauResult] = useState<BacktestPlateauResponse | null>(null)
  const [plateauError, setPlateauError] = useState<string | null>(null)
  const [plateauApplyRank, setPlateauApplyRank] = useState(1)
  const [plateauHeatmapXAxis, setPlateauHeatmapXAxis] = useState<PlateauAxisKey>('window_days')
  const [plateauHeatmapYAxis, setPlateauHeatmapYAxis] = useState<PlateauAxisKey>('min_score')
  const [plateauHeatmapMetric, setPlateauHeatmapMetric] = useState<PlateauMetricKey>('score')
  const [plateauHeatmapShowBestPath, setPlateauHeatmapShowBestPath] = useState(true)
  const [plateauHeatmapShowCellLabel, setPlateauHeatmapShowCellLabel] = useState(false)
  const [plateauHeatmapSelectedCoord, setPlateauHeatmapSelectedCoord] = useState<[string, string] | null>(null)
  const [plateauBrushSelectedKeys, setPlateauBrushSelectedKeys] = useState<string[]>([])
  const [plateauCandidatePoints, setPlateauCandidatePoints] = useState<BacktestPlateauPoint[]>([])
  const [plateauCandidatePickRank, setPlateauCandidatePickRank] = useState(1)
  const [plateauSavedPresets, setPlateauSavedPresets] = useState<BacktestPlateauPreset[]>(() => loadBacktestPlateauPresets())
  const [plateauSavedPresetId, setPlateauSavedPresetId] = useState<string | null>(null)
  const [tradePage, setTradePage] = useState(1)
  const [tradePageSize, setTradePageSize] = useState(initialDraft.trades_page_size)
  const [runError, setRunError] = useState<string | null>(null)
  const tasksById = useBacktestTaskStore((state) => state.tasksById)
  const activeTaskIds = useBacktestTaskStore((state) => state.activeTaskIds)
  const selectedTaskId = useBacktestTaskStore((state) => state.selectedTaskId)
  const enqueueTask = useBacktestTaskStore((state) => state.enqueueTask)
  const upsertTaskStatus = useBacktestTaskStore((state) => state.upsertTaskStatus)
  const setSelectedTask = useBacktestTaskStore((state) => state.setSelectedTask)

  const taskOptions = useMemo(
    () =>
      Object.values(tasksById)
        .sort((left, right) => {
          const leftTs = Date.parse(left.progress.updated_at || left.progress.started_at || '')
          const rightTs = Date.parse(right.progress.updated_at || right.progress.started_at || '')
          return rightTs - leftTs
        })
        .map((task) => ({
          value: task.task_id,
          label: `${taskStatusLabel(task.status)} | ${task.task_id.slice(0, 12)} | ${task.progress.updated_at}`,
        })),
    [tasksById],
  )
  const taskStatus = selectedTaskId ? tasksById[selectedTaskId] ?? null : null
  const taskProgress = taskStatus?.progress
  const result = taskStatus?.result ?? undefined
  const runningTaskCount = activeTaskIds.length

  function applyRunMeta(nextRunId: string, asOfDate?: string) {
    setMode('trend_pool')
    setTrendStep('auto')
    setRunId(nextRunId)
    if (!asOfDate) return
    const parsed = dayjs(asOfDate)
    if (!parsed.isValid()) return
    setRange((current) => {
      const spanDays = Math.max(30, current[1].diff(current[0], 'day'))
      return [parsed.subtract(spanDays, 'day'), parsed]
    })
  }

  function readScreenerRunMetaFromStorage() {
    try {
      const raw = window.localStorage.getItem(SCREENER_CACHE_KEY)
      if (!raw) return null
      const parsed = JSON.parse(raw) as {
        run_meta?: { runId?: unknown; asOfDate?: unknown }
        form_values?: { board_filters?: unknown }
      }
      const runIdText = typeof parsed?.run_meta?.runId === 'string' ? parsed.run_meta.runId.trim() : ''
      const asOfDateText =
        typeof parsed?.run_meta?.asOfDate === 'string' ? parsed.run_meta.asOfDate.trim() : ''
      const boardFilters = sanitizeBoardFilters(parsed?.form_values?.board_filters)
      if (!runIdText) return null
      return {
        runId: runIdText,
        asOfDate: asOfDateText || undefined,
        boardFilters: boardFilters.length > 0 ? boardFilters : undefined,
      }
    } catch {
      return null
    }
  }

  useEffect(() => {
    const draft: BacktestFormDraft = {
      mode,
      trend_step: trendStep,
      pool_roll_mode: poolRollMode,
      run_id: runId,
      board_filters: boardFilters,
      date_from: range[0].format('YYYY-MM-DD'),
      date_to: range[1].format('YYYY-MM-DD'),
      window_days: windowDays,
      min_score: minScore,
      require_sequence: requireSequence,
      min_event_count: minEventCount,
      entry_events: entryEvents,
      exit_events: exitEvents,
      initial_capital: initialCapital,
      position_pct: toRatio(positionPctPercent, TRADE_BACKTEST_DEFAULTS.positionPct, 0.0001, 1),
      max_positions: maxPositions,
      stop_loss: toRatio(stopLossPercent, TRADE_BACKTEST_DEFAULTS.stopLoss, 0, 0.5),
      take_profit: toRatio(takeProfitPercent, TRADE_BACKTEST_DEFAULTS.takeProfit, 0, 1.5),
      max_hold_days: maxHoldDays,
      fee_bps: feeBps,
      prioritize_signals: prioritizeSignals,
      priority_mode: priorityMode,
      priority_topk_per_day: priorityTopK,
      enforce_t1: enforceT1,
      max_symbols: maxSymbols,
      trades_page_size: tradePageSize,
    }
    persistBacktestDraft(draft)
  }, [
    mode,
    trendStep,
    poolRollMode,
    runId,
    boardFilters,
    range,
    windowDays,
    minScore,
    requireSequence,
    minEventCount,
    entryEvents,
    exitEvents,
    initialCapital,
    positionPctPercent,
    maxPositions,
    stopLossPercent,
    takeProfitPercent,
    maxHoldDays,
    feeBps,
    prioritizeSignals,
    priorityMode,
    priorityTopK,
    enforceT1,
    maxSymbols,
    tradePageSize,
  ])

  const startTaskMutation = useMutation({
    mutationFn: startBacktestTask,
    onSuccess: (payload) => {
      enqueueTask(payload.task_id, poolRollMode)
      setSelectedTask(payload.task_id)
      setRunError(null)
      message.info('回测任务已提交，正在按日期滚动计算...')
    },
    onError: (error) => {
      const text = formatApiError(error)
      setRunError(text)
      message.error(text)
    },
  })

  const runPlateauMutation = useMutation({
    mutationFn: runBacktestPlateau,
    onSuccess: (payload) => {
      setPlateauResult(payload)
      setPlateauError(null)
      message.success(`收益平原评估完成：${payload.evaluated_combinations} 组`)
    },
    onError: (error) => {
      const text = formatApiError(error)
      setPlateauError(text)
      message.error(text)
    },
  })

  const controlTaskMutation = useMutation({
    mutationFn: async (payload: { action: 'pause' | 'resume' | 'cancel'; taskId: string }) => {
      if (payload.action === 'pause') return pauseBacktestTask(payload.taskId)
      if (payload.action === 'resume') return resumeBacktestTask(payload.taskId)
      return cancelBacktestTask(payload.taskId)
    },
    onSuccess: (status, variables) => {
      upsertTaskStatus(status)
      if (variables.action === 'pause') {
        message.info(`任务已暂停：${status.task_id}`)
      } else if (variables.action === 'resume') {
        message.success(`任务已继续：${status.task_id}`)
      } else {
        message.warning(`任务已停止：${status.task_id}`)
      }
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  useEffect(() => {
    setTradePage(1)
  }, [result?.trades])

  useEffect(() => {
    setPlateauApplyRank(1)
  }, [plateauResult?.generated_at])

  useEffect(() => {
    setPlateauHeatmapSelectedCoord(null)
    setPlateauBrushSelectedKeys([])
  }, [plateauResult?.generated_at, plateauHeatmapXAxis, plateauHeatmapYAxis, plateauHeatmapMetric])

  useEffect(() => {
    if (plateauCandidatePoints.length <= 0) {
      if (plateauCandidatePickRank !== 1) setPlateauCandidatePickRank(1)
      return
    }
    if (plateauCandidatePickRank < 1 || plateauCandidatePickRank > plateauCandidatePoints.length) {
      setPlateauCandidatePickRank(1)
    }
  }, [plateauCandidatePickRank, plateauCandidatePoints.length])

  useEffect(() => {
    persistBacktestPlateauPresets(plateauSavedPresets)
  }, [plateauSavedPresets])

  useEffect(() => {
    if (plateauSavedPresets.length <= 0) {
      if (plateauSavedPresetId !== null) setPlateauSavedPresetId(null)
      return
    }
    if (!plateauSavedPresetId || !plateauSavedPresets.some((item) => item.id === plateauSavedPresetId)) {
      setPlateauSavedPresetId(plateauSavedPresets[0].id)
    }
  }, [plateauSavedPresetId, plateauSavedPresets])

  useEffect(() => {
    if (selectedTaskId) return
    if (taskOptions.length <= 0) return
    const firstTaskId = String(taskOptions[0]?.value || '').trim()
    if (!firstTaskId) return
    setSelectedTask(firstTaskId)
  }, [selectedTaskId, setSelectedTask, taskOptions])

  const equityOption = useMemo(() => {
    const curve = result?.equity_curve ?? []
    return {
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: curve.map((row) => row.date) },
      yAxis: { type: 'value', scale: true },
      series: [
        {
          type: 'line',
          smooth: true,
          data: curve.map((row) => row.equity),
          lineStyle: { width: 2, color: '#0f8b6f' },
          areaStyle: { color: 'rgba(15,139,111,0.16)' },
        },
      ],
      grid: { left: 48, right: 20, top: 24, bottom: 36 },
    }
  }, [result?.equity_curve])

  const drawdownOption = useMemo(() => {
    const curve = result?.drawdown_curve ?? []
    return {
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: curve.map((row) => row.date) },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(1)}%` },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          data: curve.map((row) => row.drawdown),
          lineStyle: { width: 2, color: '#c4473d' },
          areaStyle: { color: 'rgba(196,71,61,0.16)' },
        },
      ],
      grid: { left: 48, right: 20, top: 24, bottom: 36 },
    }
  }, [result?.drawdown_curve])

  function buildBacktestPayload(effectiveBoardFilters?: BoardFilter[]) {
    return {
      mode,
      run_id: runId.trim() || undefined,
      trend_step: trendStep,
      pool_roll_mode: poolRollMode,
      board_filters: mode === 'trend_pool' ? effectiveBoardFilters : undefined,
      date_from: range[0].format('YYYY-MM-DD'),
      date_to: range[1].format('YYYY-MM-DD'),
      window_days: windowDays,
      min_score: minScore,
      require_sequence: requireSequence,
      min_event_count: minEventCount,
      entry_events: entryEvents,
      exit_events: exitEvents,
      initial_capital: initialCapital,
      position_pct: toRatio(positionPctPercent, TRADE_BACKTEST_DEFAULTS.positionPct, 0.0001, 1),
      max_positions: maxPositions,
      stop_loss: toRatio(stopLossPercent, TRADE_BACKTEST_DEFAULTS.stopLoss, 0, 0.5),
      take_profit: toRatio(takeProfitPercent, TRADE_BACKTEST_DEFAULTS.takeProfit, 0, 1.5),
      max_hold_days: maxHoldDays,
      fee_bps: feeBps,
      prioritize_signals: prioritizeSignals,
      priority_mode: priorityMode,
      priority_topk_per_day: priorityTopK,
      enforce_t1: enforceT1,
      max_symbols: maxSymbols,
    }
  }

  function handleRun() {
    if (runLoading) return
    if (entryEvents.length === 0 || exitEvents.length === 0) {
      message.warning('请至少选择一个入场事件和离场事件')
      return
    }
    const cached = readScreenerRunMetaFromStorage()
    const effectiveBoardFilters = cached?.boardFilters?.length ? cached.boardFilters : boardFilters
    const shouldApplyBoardFilters = mode === 'trend_pool'
    if (shouldApplyBoardFilters && effectiveBoardFilters.length === 0) {
      message.warning('请至少选择一个板块后再回测')
      return
    }
    if (cached?.boardFilters?.length) {
      setBoardFilters(cached.boardFilters)
    }
    const payload = buildBacktestPayload(shouldApplyBoardFilters ? effectiveBoardFilters : undefined)
    setRunError(null)
    startTaskMutation.mutate(payload)
  }

  function handleBindLatestRunId() {
    const cached = readScreenerRunMetaFromStorage()
    if (cached?.runId) {
      applyRunMeta(cached.runId, cached.asOfDate)
      if (cached.boardFilters?.length) {
        setBoardFilters(cached.boardFilters)
      }
      message.success(`已从本地筛选缓存带入任务：${cached.runId}`)
      return
    }
    message.info('未找到本地筛选缓存，请先在“趋势选股”页执行一次选股，或手动填写 run_id。')
  }

  function handleRunPlateau() {
    if (runPlateauMutation.isPending) return
    if (entryEvents.length === 0 || exitEvents.length === 0) {
      message.warning('请至少选择一个入场事件和离场事件')
      return
    }
    const cached = readScreenerRunMetaFromStorage()
    const effectiveBoardFilters = cached?.boardFilters?.length ? cached.boardFilters : boardFilters
    if (mode === 'trend_pool' && effectiveBoardFilters.length === 0) {
      message.warning('请至少选择一个板块后再执行收益平原')
      return
    }
    if (cached?.boardFilters?.length) {
      setBoardFilters(cached.boardFilters)
    }
    const stopLossPctList = parseNumericList(plateauStopLossPctListRaw, {
      integer: false,
      min: 0,
      max: 50,
      precision: 4,
    })
    const takeProfitPctList = parseNumericList(plateauTakeProfitPctListRaw, {
      integer: false,
      min: 0,
      max: 150,
      precision: 4,
    })
    const positionPctList = parseNumericList(plateauPositionPctListRaw, {
      integer: false,
      min: 1,
      max: 100,
      precision: 4,
    })
    const samplePoints = Math.max(1, Math.min(2000, Number(plateauSamplePoints || 120)))
    const payload = {
      base_payload: buildBacktestPayload(mode === 'trend_pool' ? effectiveBoardFilters : undefined),
      sampling_mode: plateauSamplingMode,
      window_days_list: parseNumericList(plateauWindowListRaw, {
        integer: true,
        min: 20,
        max: 240,
      }),
      min_score_list: parseNumericList(plateauMinScoreListRaw, {
        integer: false,
        min: 0,
        max: 100,
        precision: 4,
      }),
      stop_loss_list: stopLossPctList.map((item) => Number((item / 100).toFixed(6))),
      take_profit_list: takeProfitPctList.map((item) => Number((item / 100).toFixed(6))),
      max_positions_list: parseNumericList(plateauMaxPositionsListRaw, {
        integer: true,
        min: 1,
        max: 100,
      }),
      position_pct_list: positionPctList.map((item) => Number((item / 100).toFixed(6))),
      max_symbols_list: parseNumericList(plateauMaxSymbolsListRaw, {
        integer: true,
        min: 20,
        max: 2000,
      }),
      priority_topk_per_day_list: parseNumericList(plateauTopKListRaw, {
        integer: true,
        min: 0,
        max: 500,
      }),
      sample_points: samplePoints,
      random_seed: plateauRandomSeed ?? undefined,
      max_points: samplePoints,
    }
    setPlateauError(null)
    runPlateauMutation.mutate(payload)
  }

  function applyPlateauPointToForm(point: BacktestPlateauPoint, rankLabel?: string) {
    if (point.error) {
      message.warning('该参数组评估失败，无法回填')
      return
    }
    setWindowDays(Number(point.params.window_days))
    setMinScore(Number(point.params.min_score))
    setStopLossPercent(toPercent(Number(point.params.stop_loss)))
    setTakeProfitPercent(toPercent(Number(point.params.take_profit)))
    setMaxPositions(Number(point.params.max_positions))
    setPositionPctPercent(toPercent(Number(point.params.position_pct)))
    setMaxSymbols(Number(point.params.max_symbols))
    setPriorityTopK(Number(point.params.priority_topk_per_day))
    setRunError(null)
    const prefix = rankLabel ? `${rankLabel}参数已回填` : '参数已回填'
    message.success(`${prefix}：信号窗口=${point.params.window_days}，最低评分=${point.params.min_score.toFixed(2)}`)
  }

  const taskRunning = taskStatus?.status === 'running' || taskStatus?.status === 'pending' || taskStatus?.status === 'paused'
  const runLoading = startTaskMutation.isPending
  const plateauLoading = runPlateauMutation.isPending
  const plateauBestPoint = plateauResult?.best_point ?? null
  const plateauValidPoints = useMemo(
    () => (plateauResult?.points ?? []).filter((row) => !row.error),
    [plateauResult?.points],
  )
  const plateauTopRankOptions = useMemo(
    () =>
      plateauValidPoints.slice(0, 20).map((row, idx) => ({
        value: idx + 1,
        label: `第${idx + 1}名 | 评分 ${row.score.toFixed(3)} | 收益 ${formatPct(row.stats.total_return)}`,
      })),
    [plateauValidPoints],
  )
  const plateauTableRows = useMemo<BacktestPlateauTableRow[]>(
    () =>
      (plateauResult?.points ?? []).map((row, index) => ({
        ...row,
        __rank: index + 1,
        __rowKey: buildPlateauRowKey(row, index),
      })),
    [plateauResult?.points],
  )
  const selectedRankPoint = plateauValidPoints[plateauApplyRank - 1] ?? null
  const plateauColumnsWithAction: ColumnsType<BacktestPlateauTableRow> = [
    ...plateauColumns,
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_value, row) => (
        <Button
          size="small"
          disabled={Boolean(row.error)}
          onClick={() => applyPlateauPointToForm(row, `第${row.__rank}名`)}
        >
          回填
        </Button>
      ),
    },
  ]
  const plateauScoreBarOption = useMemo(() => {
    const rows = plateauValidPoints.slice(0, 30)
    if (rows.length === 0) return null
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      grid: {
        left: 56,
        right: 20,
        top: 24,
        bottom: 56,
      },
      xAxis: {
        type: 'category',
        data: rows.map((_row, idx) => `第${idx + 1}名`),
      },
      yAxis: {
        type: 'value',
        name: '评分',
      },
      series: [
        {
          type: 'bar',
          data: rows.map((row) => Number(row.score.toFixed(4))),
          itemStyle: {
            color: '#0f8b6f',
            borderRadius: [3, 3, 0, 0],
          },
        },
      ],
    }
  }, [plateauValidPoints])
  const plateauHeatmapView = useMemo(() => {
    const xAxisLabel = PLATEAU_AXIS_LABEL_MAP[plateauHeatmapXAxis]
    const yAxisLabel = PLATEAU_AXIS_LABEL_MAP[plateauHeatmapYAxis]
    const metricLabel = PLATEAU_METRIC_LABEL_MAP[plateauHeatmapMetric]
    const rows = plateauValidPoints
    if (rows.length === 0) {
      return {
        option: null,
        reason: '暂无可视化数据，请先执行收益平原扫描。',
        chartHeight: 320,
        xAxisLabel,
        yAxisLabel,
        metricLabel,
        pointByCategory: new Map<string, BacktestPlateauPoint>(),
        cellKeyByDataIndex: [] as string[],
      }
    }
    if (plateauHeatmapXAxis === plateauHeatmapYAxis) {
      return {
        option: null,
        reason: '横轴与纵轴不能相同，请分别选择不同参数。',
        chartHeight: 320,
        xAxisLabel,
        yAxisLabel,
        metricLabel,
        pointByCategory: new Map<string, BacktestPlateauPoint>(),
        cellKeyByDataIndex: [] as string[],
      }
    }

    const xAxisValues = Array.from(
      new Set(rows.map((row) => getPlateauAxisRawValue(row, plateauHeatmapXAxis))),
    ).sort((a, b) => a - b)
    const yAxisValues = Array.from(
      new Set(rows.map((row) => getPlateauAxisRawValue(row, plateauHeatmapYAxis))),
    ).sort((a, b) => a - b)

    if (xAxisValues.length <= 1 || yAxisValues.length <= 1) {
      return {
        option: null,
        reason: `当前结果中“${xAxisLabel}”或“${yAxisLabel}”只有一个取值，无法绘制二维方块热力图。`,
        chartHeight: 320,
        xAxisLabel,
        yAxisLabel,
        metricLabel,
        pointByCategory: new Map<string, BacktestPlateauPoint>(),
        cellKeyByDataIndex: [] as string[],
      }
    }

    const metricByCell = new Map<string, number>()
    const bestPointByCell = new Map<string, BacktestPlateauPoint>()
    rows.forEach((row) => {
      const xValue = getPlateauAxisRawValue(row, plateauHeatmapXAxis)
      const yValue = getPlateauAxisRawValue(row, plateauHeatmapYAxis)
      const metric = getPlateauMetricValue(row, plateauHeatmapMetric)
      const key = buildPlateauCellKey(xValue, yValue)
      const prev = metricByCell.get(key)
      if (typeof prev !== 'number' || metric > prev) {
        metricByCell.set(key, metric)
        bestPointByCell.set(key, row)
      }
    })

    const xAxisCategories = xAxisValues.map((value) => formatPlateauAxisCategory(plateauHeatmapXAxis, value))
    const yAxisCategories = yAxisValues.map((value) => formatPlateauAxisCategory(plateauHeatmapYAxis, value))
    const heatmapData: Array<[string, string, number]> = []
    const cellKeyByDataIndex: string[] = []
    const metricByCategory = new Map<string, number>()
    const pointByCategory = new Map<string, BacktestPlateauPoint>()
    let minMetricValue = Number.POSITIVE_INFINITY
    let maxMetricValue = Number.NEGATIVE_INFINITY

    xAxisValues.forEach((xValue) => {
      yAxisValues.forEach((yValue) => {
        const metric = metricByCell.get(buildPlateauCellKey(xValue, yValue))
        if (typeof metric !== 'number') return
        const xCategory = formatPlateauAxisCategory(plateauHeatmapXAxis, xValue)
        const yCategory = formatPlateauAxisCategory(plateauHeatmapYAxis, yValue)
        const categoryKey = `${xCategory}|${yCategory}`
        const roundedMetric = Number(metric.toFixed(6))
        heatmapData.push([xCategory, yCategory, roundedMetric])
        cellKeyByDataIndex.push(categoryKey)
        metricByCategory.set(categoryKey, roundedMetric)
        const point = bestPointByCell.get(buildPlateauCellKey(xValue, yValue))
        if (point) {
          pointByCategory.set(categoryKey, point)
        }
        minMetricValue = Math.min(minMetricValue, roundedMetric)
        maxMetricValue = Math.max(maxMetricValue, roundedMetric)
      })
    })

    if (heatmapData.length === 0) {
      return {
        option: null,
        reason: '当前参数组合没有形成有效二维网格数据，请扩大参数扫描范围后重试。',
        chartHeight: 320,
        xAxisLabel,
        yAxisLabel,
        metricLabel,
        pointByCategory: new Map<string, BacktestPlateauPoint>(),
        cellKeyByDataIndex: [] as string[],
      }
    }

    const bestPathData: Array<[string, string]> = []
    if (plateauHeatmapShowBestPath) {
      xAxisValues.forEach((xValue) => {
        let bestMetric = Number.NEGATIVE_INFINITY
        let bestYCategory: string | null = null
        yAxisValues.forEach((yValue) => {
          const metric = metricByCell.get(buildPlateauCellKey(xValue, yValue))
          if (typeof metric !== 'number') return
          if (metric > bestMetric) {
            bestMetric = metric
            bestYCategory = formatPlateauAxisCategory(plateauHeatmapYAxis, yValue)
          }
        })
        if (bestYCategory) {
          bestPathData.push([
            formatPlateauAxisCategory(plateauHeatmapXAxis, xValue),
            bestYCategory,
          ])
        }
      })
    }

    const visualMin = Number.isFinite(minMetricValue) ? Number(minMetricValue.toFixed(6)) : 0
    const visualMax = Number.isFinite(maxMetricValue) ? Number(maxMetricValue.toFixed(6)) : 1
    const chartHeight = Math.max(260, Math.min(480, yAxisCategories.length * 24 + 110))
    const selectedKey = plateauHeatmapSelectedCoord
      ? `${plateauHeatmapSelectedCoord[0]}|${plateauHeatmapSelectedCoord[1]}`
      : ''
    const selectedCoordData =
      selectedKey && pointByCategory.has(selectedKey) && plateauHeatmapSelectedCoord
        ? [[plateauHeatmapSelectedCoord[0], plateauHeatmapSelectedCoord[1]]]
        : []

    const option = {
      tooltip: {
        trigger: 'item',
        formatter: (params: { value?: [string, string, number] }) => {
          const value = params?.value
          if (!Array.isArray(value) || value.length < 3) return ''
          const [xCategory, yCategory, metric] = value
          const actualMetric = metricByCategory.get(`${xCategory}|${yCategory}`) ?? Number(metric)
          return [
            `${xAxisLabel}: ${xCategory}`,
            `${yAxisLabel}: ${yCategory}`,
            `${metricLabel}: ${formatPlateauMetricValue(plateauHeatmapMetric, actualMetric)}`,
          ].join('<br/>')
        },
      },
      grid: {
        left: 88,
        right: 64,
        top: 24,
        bottom: 84,
      },
      xAxis: {
        type: 'category',
        data: xAxisCategories,
        name: xAxisLabel,
        nameLocation: 'middle',
        nameGap: 34,
        axisLabel: {
          interval: 0,
          hideOverlap: true,
          rotate: xAxisCategories.length > 8 ? 26 : 0,
          fontSize: 11,
        },
      },
      yAxis: {
        type: 'category',
        data: yAxisCategories,
        name: yAxisLabel,
        nameLocation: 'middle',
        nameGap: 56,
        axisLabel: {
          hideOverlap: true,
          fontSize: 11,
        },
      },
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: 0,
          filterMode: 'none',
        },
        {
          type: 'inside',
          yAxisIndex: 0,
          filterMode: 'none',
        },
        {
          type: 'slider',
          yAxisIndex: 0,
          right: 18,
          top: 36,
          bottom: 78,
          width: 12,
          filterMode: 'none',
        },
      ],
      visualMap: {
        min: visualMin,
        max: visualMax,
        dimension: 2,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 18,
        text: [metricLabel, ''],
        inRange: {
          color: ['#dff5e8', '#8fd7b8', '#3aaf87', '#0f8b6f'],
        },
      },
      toolbox: {
        right: 8,
        top: 2,
        feature: {
          brush: {
            type: ['rect', 'clear'],
          },
        },
      },
      brush: {
        xAxisIndex: 'all',
        yAxisIndex: 'all',
        brushLink: 'all',
        inBrush: {
          opacity: 1,
        },
        outOfBrush: {
          opacity: 0.25,
        },
      },
      series: [
        {
          type: 'heatmap',
          data: heatmapData,
          itemStyle: {
            borderColor: 'rgba(255,255,255,0.9)',
            borderWidth: 1,
          },
          label: {
            show: plateauHeatmapShowCellLabel,
            color: '#123026',
            fontSize: 10,
            formatter: (params: { value?: [string, string, number] }) => {
              const metric = Number(params?.value?.[2] ?? 0)
              return formatPlateauMetricValue(plateauHeatmapMetric, metric)
            },
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: 'rgba(15, 139, 111, 0.35)',
            },
          },
          z: 1,
        },
        ...(bestPathData.length > 0
          ? [
              {
                type: 'line',
                data: bestPathData,
                showSymbol: true,
                symbol: 'diamond',
                symbolSize: 9,
                lineStyle: {
                  color: '#fa8c16',
                  width: 2,
                },
                itemStyle: {
                  color: '#fa8c16',
                  borderColor: '#fff',
                  borderWidth: 1,
                },
                z: 3,
              },
            ]
          : []),
        ...(selectedCoordData.length > 0
          ? [
              {
                type: 'scatter',
                data: selectedCoordData,
                symbol: 'roundRect',
                symbolSize: 14,
                itemStyle: {
                  color: '#f5222d',
                  borderColor: '#fff',
                  borderWidth: 1,
                },
                z: 4,
              },
            ]
          : []),
      ],
    }

    return {
      option,
      reason: null,
      chartHeight,
      xAxisLabel,
      yAxisLabel,
      metricLabel,
      pointByCategory,
      cellKeyByDataIndex,
    }
  }, [
    plateauHeatmapMetric,
    plateauHeatmapShowBestPath,
    plateauHeatmapShowCellLabel,
    plateauHeatmapSelectedCoord,
    plateauHeatmapXAxis,
    plateauHeatmapYAxis,
    plateauValidPoints,
  ])
  const plateauHeatmapOption = plateauHeatmapView.option
  const plateauHeatmapUnavailableReason = plateauHeatmapView.reason
  const plateauHeatmapChartHeight = plateauHeatmapView.chartHeight
  const plateauHeatmapTitle = `方块热力图（${plateauHeatmapView.xAxisLabel} × ${plateauHeatmapView.yAxisLabel}，值=${plateauHeatmapView.metricLabel}）`
  const plateauHeatmapPointByCategory = plateauHeatmapView.pointByCategory
  const plateauHeatmapCellKeyByDataIndex = plateauHeatmapView.cellKeyByDataIndex
  const plateauBrushSelectedPoints = useMemo(
    () =>
      plateauBrushSelectedKeys
        .map((key) => plateauHeatmapPointByCategory.get(key))
        .filter((item): item is BacktestPlateauPoint => Boolean(item)),
    [plateauBrushSelectedKeys, plateauHeatmapPointByCategory],
  )
  const plateauCandidateOptions = useMemo(
    () =>
      plateauCandidatePoints.map((point, index) => ({
        value: index + 1,
        label: `候选#${index + 1} | 评分 ${point.score.toFixed(3)} | 收益 ${formatPct(point.stats.total_return)}`,
      })),
    [plateauCandidatePoints],
  )
  const selectedCandidatePoint = plateauCandidatePoints[plateauCandidatePickRank - 1] ?? null
  const plateauSavedPresetOptions = useMemo(
    () =>
      plateauSavedPresets.map((item, index) => ({
        value: item.id,
        label: `收藏#${index + 1} | ${item.name} | ${item.saved_at}`,
      })),
    [plateauSavedPresets],
  )
  const selectedSavedPreset = useMemo(
    () => plateauSavedPresets.find((item) => item.id === plateauSavedPresetId) ?? null,
    [plateauSavedPresetId, plateauSavedPresets],
  )
  const plateauSavedPresetColumns = useMemo<ColumnsType<BacktestPlateauPreset>>(
    () => [
      {
        title: '收藏名',
        dataIndex: 'name',
        width: 280,
      },
      {
        title: '保存时间',
        dataIndex: 'saved_at',
        width: 170,
      },
      {
        title: '评分',
        width: 90,
        render: (_value, row) => row.point.score.toFixed(3),
      },
      {
        title: '收益',
        width: 100,
        render: (_value, row) => formatPct(row.point.stats.total_return),
      },
      {
        title: '参数摘要',
        width: 360,
        render: (_value, row) => {
          const p = row.point.params
          return `window=${p.window_days}, min_score=${Number(p.min_score).toFixed(2)}, stop_loss=${(Number(p.stop_loss) * 100).toFixed(2)}%, take_profit=${(Number(p.take_profit) * 100).toFixed(2)}%, pos=${p.max_positions}`
        },
      },
      {
        title: '操作',
        key: 'action',
        width: 150,
        render: (_value, row) => (
          <Space size={6}>
            <Button size="small" onClick={() => applyPlateauPointToForm(row.point, '收藏参数')}>
              回填
            </Button>
            <Button
              size="small"
              danger
              onClick={() => {
                setPlateauSavedPresets((prev) => prev.filter((item) => item.id !== row.id))
                if (plateauSavedPresetId === row.id) setPlateauSavedPresetId(null)
              }}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ],
    [applyPlateauPointToForm, plateauSavedPresetId],
  )

  function savePlateauPreset(point: BacktestPlateauPoint, sourceLabel: string) {
    if (point.error) {
      message.warning('该参数组评估失败，无法保存。')
      return
    }
    const nowText = dayjs().format('YYYY-MM-DD HH:mm:ss')
    const paramsKey = buildPlateauParamsKey(point)
    const presetName = `${sourceLabel} | 评分 ${point.score.toFixed(3)} | 收益 ${formatPct(point.stats.total_return)}`
    let persistedId = ''
    setPlateauSavedPresets((prev) => {
      const idx = prev.findIndex((item) => buildPlateauParamsKey(item.point) === paramsKey)
      if (idx >= 0) {
        const next = [...prev]
        const existing = next[idx]
        persistedId = existing.id
        next[idx] = {
          ...existing,
          name: presetName,
          saved_at: nowText,
          point,
        }
        return next
      }
      const created: BacktestPlateauPreset = {
        id: `pp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
        name: presetName,
        saved_at: nowText,
        point,
      }
      persistedId = created.id
      return [created, ...prev].slice(0, 300)
    })
    if (persistedId) {
      setPlateauSavedPresetId(persistedId)
    }
    message.success(`已保存参数：${presetName}`)
  }

  function handleApplySavedPreset() {
    if (!selectedSavedPreset) {
      message.info('请先选择一个收藏参数。')
      return
    }
    applyPlateauPointToForm(selectedSavedPreset.point, '收藏参数')
  }

  function handleDeleteSavedPreset() {
    if (!selectedSavedPreset) {
      message.info('请先选择一个收藏参数。')
      return
    }
    const deletingId = selectedSavedPreset.id
    setPlateauSavedPresets((prev) => prev.filter((item) => item.id !== deletingId))
    if (plateauSavedPresetId === deletingId) {
      setPlateauSavedPresetId(null)
    }
    message.success('已删除收藏参数。')
  }

  function appendPointsToCandidateSet(points: BacktestPlateauPoint[], sourceLabel: string) {
    if (points.length <= 0) {
      message.info(`未从${sourceLabel}获取可加入的参数组。`)
      return
    }
    let addedCount = 0
    setPlateauCandidatePoints((prev) => {
      const next = [...prev]
      const seen = new Set(prev.map((item) => buildPlateauParamsKey(item)))
      points.forEach((point) => {
        const key = buildPlateauParamsKey(point)
        if (seen.has(key)) return
        seen.add(key)
        next.push(point)
        addedCount += 1
      })
      return next
    })
    setPlateauCandidatePickRank(1)
    if (addedCount > 0) {
      message.success(`已从${sourceLabel}加入候选参数 ${addedCount} 组。`)
    } else {
      message.info(`候选参数集中已包含${sourceLabel}选中的参数组。`)
    }
  }

  function handleAddBrushSelectionToCandidates() {
    appendPointsToCandidateSet(plateauBrushSelectedPoints, '框选区域')
  }

  function handleApplySelectedCandidatePoint() {
    if (!selectedCandidatePoint) {
      message.info('请先选择一个候选参数组。')
      return
    }
    applyPlateauPointToForm(selectedCandidatePoint, `候选#${plateauCandidatePickRank}`)
  }

  function handleClearCandidatePoints() {
    setPlateauCandidatePoints([])
    setPlateauCandidatePickRank(1)
  }

  const plateauHeatmapOnEvents = useMemo(
    () => ({
      click: (params: { seriesType?: string; value?: unknown }) => {
        if (params?.seriesType !== 'heatmap') return
        const value = params?.value
        if (!Array.isArray(value) || value.length < 2) return
        const xCategory = String(value[0] ?? '').trim()
        const yCategory = String(value[1] ?? '').trim()
        if (!xCategory || !yCategory) return
        const key = `${xCategory}|${yCategory}`
        const point = plateauHeatmapPointByCategory.get(key)
        if (!point) return
        setPlateauHeatmapSelectedCoord([xCategory, yCategory])
        applyPlateauPointToForm(point, `热力图点(${xCategory}, ${yCategory})`)
      },
      brushSelected: (params: {
        batch?: Array<{
          selected?: Array<{
            seriesIndex?: number
            dataIndex?: number[]
          }>
        }>
      }) => {
        const indexSet = new Set<number>()
        const batches = Array.isArray(params?.batch) ? params.batch : []
        batches.forEach((batchItem) => {
          const selectedSeries = Array.isArray(batchItem?.selected) ? batchItem.selected : []
          selectedSeries.forEach((seriesItem) => {
            if (typeof seriesItem?.seriesIndex === 'number' && seriesItem.seriesIndex !== 0) return
            const dataIndices = Array.isArray(seriesItem?.dataIndex) ? seriesItem.dataIndex : []
            dataIndices.forEach((idx) => {
              const numericIndex = Number(idx)
              if (Number.isInteger(numericIndex) && numericIndex >= 0) {
                indexSet.add(numericIndex)
              }
            })
          })
        })
        const keys = Array.from(indexSet)
          .sort((a, b) => a - b)
          .map((idx) => plateauHeatmapCellKeyByDataIndex[idx])
          .filter((item): item is string => Boolean(item))
        setPlateauBrushSelectedKeys(keys)
      },
    }),
    [applyPlateauPointToForm, plateauHeatmapCellKeyByDataIndex, plateauHeatmapPointByCategory],
  )
  const effectiveRunError =
    runError
    || (taskStatus?.status === 'failed' ? (taskStatus.error?.trim() || '回测任务失败') : null)
  const taskStageRows = useMemo(() => {
    const rows = Array.isArray(taskProgress?.stage_timings) ? taskProgress.stage_timings : []
    const normalized = rows
      .map((row) => ({
        stageKey: String(row?.stage_key || '').trim(),
        label: String(row?.label || '').trim() || '未命名阶段',
        elapsedMs: Math.max(0, Number(row?.elapsed_ms || 0)),
      }))
      .filter((row) => Boolean(row.stageKey))
    const totalMs = normalized.reduce((acc, row) => acc + row.elapsedMs, 0)
    return {
      totalMs,
      rows: normalized.map((row) => ({
        ...row,
        elapsedSecText: `${(row.elapsedMs / 1000).toFixed(2)}s`,
        shareText: totalMs > 0 ? `${((row.elapsedMs / totalMs) * 100).toFixed(1)}%` : '0.0%',
      })),
    }
  }, [taskProgress?.stage_timings])

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="策略回测" subtitle="回放历史信号，评估策略收益、回撤与执行质量。" />

      <Card>
        <Row gutter={[12, 12]}>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>回测范围</span>
              <Radio.Group
                value={mode}
                optionType="button"
                onChange={(event) => setMode(event.target.value)}
                options={[
                  { label: '趋势池', value: 'trend_pool' },
                  { label: '全市场', value: 'full_market' },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>趋势池阶段</span>
              <Select
                value={trendStep}
                onChange={(value) => setTrendStep(value)}
                options={[
                  { value: 'auto', label: 'auto（自动）' },
                  { value: 'step1', label: 'step1' },
                  { value: 'step2', label: 'step2' },
                  { value: 'step3', label: 'step3' },
                  { value: 'step4', label: 'step4' },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>滚动模式</span>
              <Radio.Group
                value={poolRollMode}
                optionType="button"
                onChange={(event) => setPoolRollMode(event.target.value)}
                options={[
                  { label: '每日滚动', value: 'daily' },
                  { label: '每周滚动', value: 'weekly' },
                  { label: '持仓触发', value: 'position' },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>筛选任务 run_id（可选）</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input
                  value={runId}
                  onChange={(event) => setRunId(event.target.value)}
                  placeholder="请输入筛选任务 run_id"
                />
                <Button onClick={handleBindLatestRunId}>
                  带入最新筛选
                </Button>
              </div>
            </Space>
          </Col>

          {mode === 'full_market' ? (
            <Col xs={24}>
              <Alert
                type="warning"
                showIcon
                title={
                  poolRollMode === 'daily'
                    ? '全市场-每日滚动：每个交易日全量重算候选池，结果最严格，耗时最高。'
                    : poolRollMode === 'weekly'
                      ? '全市场-每周滚动：每周首个交易日重算候选池，其余交易日沿用。'
                      : '全市场-持仓触发：首日建池，卖出后下一交易日重算并补仓。'
                }
                description={
                  poolRollMode === 'position'
                    ? '该模式更贴近“卖出后再补仓”的实盘节奏；仍建议控制回测区间与最大股票数。'
                    : '该模式计算量较大，建议缩短区间或降低“最大股票数”，并通过任务进度面板观察执行状态。'
                }
              />
            </Col>
          ) : null}

          {mode === 'trend_pool' ? (
            <Col xs={24}>
              <Alert
                type={poolRollMode === 'position' ? 'info' : 'warning'}
                showIcon
                title={
                  poolRollMode === 'daily'
                    ? '每日滚动：每个交易日重算一次股票池，最严格，耗时最长。'
                    : poolRollMode === 'weekly'
                      ? '每周滚动：每周首个交易日重算股票池，速度更快。'
                      : '持仓触发：首日建池，后续在卖出后的下一交易日重算并补仓。'
                }
                description={
                  poolRollMode === 'daily' || poolRollMode === 'weekly'
                    ? '该模式使用后台任务执行，页面会按日期显示进度，耗时可能较久。'
                    : '该模式通过持仓空位触发滚动筛选，适合模拟“卖出后再补仓”的交易节奏。'
                }
              />
            </Col>
          ) : null}

          <Col xs={24} md={12}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>回测区间</span>
              <DatePicker.RangePicker
                style={{ width: '100%' }}
                value={range}
                onChange={(value) => {
                  if (value?.[0] && value?.[1]) setRange([value[0], value[1]])
                }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>信号窗口天数</span>
              <InputNumber
                min={20}
                max={240}
                value={windowDays}
                onChange={(value) => setWindowDays(Number(value || TRADE_BACKTEST_DEFAULTS.windowDays))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>最低评分</span>
              <InputNumber
                min={0}
                max={100}
                value={minScore}
                onChange={(value) => setMinScore(Number(value || TRADE_BACKTEST_DEFAULTS.minScore))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>

          <Col xs={24} md={12}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>入场事件</span>
              <Select
                mode="multiple"
                value={entryEvents}
                onChange={setEntryEvents}
                options={WY_EVENTS.map((event) => ({ label: event, value: event }))}
              />
            </Space>
          </Col>
          <Col xs={24} md={12}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>离场事件</span>
              <Select
                mode="multiple"
                value={exitEvents}
                onChange={setExitEvents}
                options={WY_EVENTS.map((event) => ({ label: event, value: event }))}
              />
            </Space>
          </Col>

          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>初始资金</span>
              <InputNumber
                min={10_000}
                max={100_000_000}
                step={10_000}
                value={initialCapital}
                onChange={(value) => setInitialCapital(Number(value || TRADE_BACKTEST_DEFAULTS.initialCapital))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>单笔仓位占比(%)</span>
              <InputNumber
                min={1}
                max={100}
                step={1}
                suffix="%"
                value={positionPctPercent}
                onChange={(value) => setPositionPctPercent(Number(value || toPercent(TRADE_BACKTEST_DEFAULTS.positionPct)))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>最大并发持仓</span>
              <InputNumber
                min={1}
                max={100}
                value={maxPositions}
                onChange={(value) => setMaxPositions(Number(value || TRADE_BACKTEST_DEFAULTS.maxPositions))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>最大股票数</span>
              <InputNumber
                min={20}
                max={2000}
                step={20}
                value={maxSymbols}
                onChange={(value) => setMaxSymbols(Number(value || TRADE_BACKTEST_DEFAULTS.maxSymbols))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>

          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>止损比例(%)</span>
              <InputNumber
                min={0}
                max={50}
                step={0.5}
                suffix="%"
                value={stopLossPercent}
                onChange={(value) => setStopLossPercent(Number(value || toPercent(TRADE_BACKTEST_DEFAULTS.stopLoss)))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>止盈比例(%)</span>
              <InputNumber
                min={0}
                max={150}
                step={0.5}
                suffix="%"
                value={takeProfitPercent}
                onChange={(value) => setTakeProfitPercent(Number(value || toPercent(TRADE_BACKTEST_DEFAULTS.takeProfit)))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>最大持仓天数</span>
              <InputNumber
                min={1}
                max={365}
                value={maxHoldDays}
                onChange={(value) => setMaxHoldDays(Number(value || TRADE_BACKTEST_DEFAULTS.maxHoldDays))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>单边费率(bps)</span>
              <InputNumber
                min={0}
                max={500}
                step={0.5}
                value={feeBps}
                onChange={(value) => setFeeBps(Number(value || TRADE_BACKTEST_DEFAULTS.feeBps))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>

          <Col xs={24} md={6}>
            <Space orientation="vertical">
              <span>要求事件顺序</span>
              <Switch checked={requireSequence} onChange={setRequireSequence} />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>最少事件数</span>
              <InputNumber
                min={0}
                max={12}
                value={minEventCount}
                onChange={(value) => setMinEventCount(Number(value || TRADE_BACKTEST_DEFAULTS.minEventCount))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical">
              <span>启用同日优先级</span>
              <Switch checked={prioritizeSignals} onChange={setPrioritizeSignals} />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical">
              <span>启用 T+1</span>
              <Switch checked={enforceT1} onChange={setEnforceT1} />
            </Space>
          </Col>

          <Col xs={24} md={12}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>优先级模式</span>
              <Radio.Group
                value={priorityMode}
                optionType="button"
                onChange={(event) => setPriorityMode(event.target.value)}
                options={[
                  { label: '阶段优先', value: 'phase_first' },
                  { label: '均衡', value: 'balanced' },
                  { label: '动量优先', value: 'momentum' },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} md={12}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>同日 TopK（0 = 不限制）</span>
              <InputNumber
                min={0}
                max={500}
                value={priorityTopK}
                onChange={(value) => setPriorityTopK(Number(value || TRADE_BACKTEST_DEFAULTS.priorityTopK))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24}>
            <Alert
              type="info"
              showIcon
              title="优先级模式说明"
              description={
                <div>
                  <div>阶段优先：同日先按阶段分，再看质量分。</div>
                  <div>均衡：同日先看质量分，再看阶段分与事件权重。</div>
                  <div>动量优先：同日先看趋势分，再看质量分。</div>
                </div>
              }
            />
          </Col>
        </Row>

        <Space style={{ marginTop: 14 }}>
          <Button type="primary" loading={runLoading} onClick={handleRun}>
            开始回测
          </Button>
          {taskStatus && (taskStatus.status === 'running' || taskStatus.status === 'pending') ? (
            <Button
              loading={controlTaskMutation.isPending && controlTaskMutation.variables?.action === 'pause'}
              onClick={() => controlTaskMutation.mutate({ action: 'pause', taskId: taskStatus.task_id })}
            >
              暂停
            </Button>
          ) : null}
          {taskStatus && taskStatus.status === 'paused' ? (
            <Button
              type="default"
              loading={controlTaskMutation.isPending && controlTaskMutation.variables?.action === 'resume'}
              onClick={() => controlTaskMutation.mutate({ action: 'resume', taskId: taskStatus.task_id })}
            >
              继续
            </Button>
          ) : null}
          {taskStatus
          && (taskStatus.status === 'running' || taskStatus.status === 'pending' || taskStatus.status === 'paused') ? (
            <Button
              danger
              loading={controlTaskMutation.isPending && controlTaskMutation.variables?.action === 'cancel'}
              onClick={() => controlTaskMutation.mutate({ action: 'cancel', taskId: taskStatus.task_id })}
            >
              停止
            </Button>
            ) : null}
          {taskOptions.length > 0 ? (
            <Select
              style={{ minWidth: 320 }}
              placeholder="选择回测任务"
              value={selectedTaskId}
              options={taskOptions}
              onChange={(value) => setSelectedTask(String(value))}
            />
          ) : null}
          {runningTaskCount > 0 ? <Tag color="processing">{`运行中 ${runningTaskCount}`}</Tag> : null}
          {taskStatus ? (
            <Tag color={taskStatusColor(taskStatus.status)}>{taskStatusLabel(taskStatus.status)}</Tag>
          ) : null}
          {result ? <Tag color="green">{`${result.range.date_from} ~ ${result.range.date_to}`}</Tag> : null}
        </Space>
      </Card>

      <Card title="收益平原（参数扫描）">
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={8}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>采样模式</span>
                <Radio.Group
                  value={plateauSamplingMode}
                  optionType="button"
                  onChange={(event) => setPlateauSamplingMode(event.target.value)}
                  options={[
                    { label: '拉丁超立方（推荐）', value: 'lhs' },
                    { label: '网格枚举', value: 'grid' },
                  ]}
                />
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>{plateauSamplingMode === 'lhs' ? '采样点数' : '最多评估点数'}</span>
                <InputNumber
                  min={1}
                  max={2000}
                  value={plateauSamplePoints}
                  onChange={(value) => setPlateauSamplePoints(Number(value || 120))}
                  style={{ width: '100%' }}
                />
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>随机种子（可选）</span>
                <InputNumber
                  min={0}
                  max={2_147_483_647}
                  value={plateauRandomSeed ?? undefined}
                  onChange={(value) => {
                    if (value === null || value === undefined) {
                      setPlateauRandomSeed(null)
                      return
                    }
                    setPlateauRandomSeed(Number(value))
                  }}
                  style={{ width: '100%' }}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>信号窗口天数列表（window_days）</span>
                <Input
                  value={plateauWindowListRaw}
                  placeholder="如: 40,60,80"
                  onChange={(event) => setPlateauWindowListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>最低评分列表（min_score）</span>
                <Input
                  value={plateauMinScoreListRaw}
                  placeholder="如: 50,55,60"
                  onChange={(event) => setPlateauMinScoreListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>止损比例列表（stop_loss，%）</span>
                <Input
                  value={plateauStopLossPctListRaw}
                  placeholder="如: 3,5,8"
                  onChange={(event) => setPlateauStopLossPctListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>止盈比例列表（take_profit，%）</span>
                <Input
                  value={plateauTakeProfitPctListRaw}
                  placeholder="如: 10,15,20"
                  onChange={(event) => setPlateauTakeProfitPctListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>最大并发持仓列表（max_positions）</span>
                <Input
                  value={plateauMaxPositionsListRaw}
                  placeholder="如: 3,5,8"
                  onChange={(event) => setPlateauMaxPositionsListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>单笔仓位占比列表（position_pct，%）</span>
                <Input
                  value={plateauPositionPctListRaw}
                  placeholder="如: 10,15,20"
                  onChange={(event) => setPlateauPositionPctListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>最大股票数列表（max_symbols）</span>
                <Input
                  value={plateauMaxSymbolsListRaw}
                  placeholder="如: 80,120,200"
                  onChange={(event) => setPlateauMaxSymbolsListRaw(event.target.value)}
                />
              </Space>
            </Col>
            <Col xs={24} md={6}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>同日 TopK 列表（priority_topk）</span>
                <Input
                  value={plateauTopKListRaw}
                  placeholder="如: 0,5,10"
                  onChange={(event) => setPlateauTopKListRaw(event.target.value)}
                />
              </Space>
            </Col>
          </Row>

          <Alert
            type="info"
            showIcon
            title="参数说明"
            description="列表为空时自动使用当前回测表单值；拉丁超立方会在区间内采样，网格枚举会按离散列表组合。"
          />

          <Space>
            <Button type="primary" ghost loading={plateauLoading} onClick={handleRunPlateau}>
              开始平原扫描
            </Button>
            {plateauResult ? (
              <Tag color="green">
                {`已评估 ${plateauResult.evaluated_combinations} / ${plateauResult.total_combinations}`}
              </Tag>
            ) : null}
            {plateauBestPoint ? (
              <Tag color="processing">
                {`最佳评分 ${plateauBestPoint.score.toFixed(3)} | 收益 ${formatPct(plateauBestPoint.stats.total_return)}`}
              </Tag>
            ) : null}
            {plateauTopRankOptions.length > 0 ? (
              <Select
                style={{ minWidth: 260 }}
                value={plateauApplyRank}
                options={plateauTopRankOptions}
                onChange={(value) => setPlateauApplyRank(Number(value))}
              />
            ) : null}
            {plateauBestPoint ? (
              <Button onClick={() => applyPlateauPointToForm(plateauBestPoint, '最佳')}>
                回填最佳参数
              </Button>
            ) : null}
            {plateauBestPoint ? (
              <Button onClick={() => savePlateauPreset(plateauBestPoint, '最佳参数')}>
                保存最佳参数
              </Button>
            ) : null}
            {selectedRankPoint ? (
              <Button onClick={() => applyPlateauPointToForm(selectedRankPoint, `第${plateauApplyRank}名`)}>
                回填第 {plateauApplyRank} 名
              </Button>
            ) : null}
            {selectedRankPoint ? (
              <Button onClick={() => savePlateauPreset(selectedRankPoint, `第${plateauApplyRank}名`)}>
                保存第 {plateauApplyRank} 名
              </Button>
            ) : null}
            {selectedCandidatePoint ? (
              <Button onClick={() => savePlateauPreset(selectedCandidatePoint, `候选#${plateauCandidatePickRank}`)}>
                保存候选参数
              </Button>
            ) : null}
          </Space>
        </Space>
      </Card>

      {plateauError ? <Alert type="error" title={plateauError} showIcon /> : null}

      {plateauResult ? (
        <>
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="总组合" value={plateauResult.total_combinations} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="评估组数" value={plateauResult.evaluated_combinations} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="最佳评分" value={plateauBestPoint?.score ?? 0} precision={3} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic
                  title="最佳收益"
                  value={(plateauBestPoint?.stats.total_return ?? 0) * 100}
                  precision={2}
                  suffix="%"
                />
              </Card>
            </Col>
          </Row>

          {plateauScoreBarOption ? (
            <Card title="评分可视化（Top 30）">
              <ReactECharts option={plateauScoreBarOption} style={{ height: 220 }} />
            </Card>
          ) : null}

          {plateauHeatmapOption ? (
            <Card title={plateauHeatmapTitle}>
              <Row gutter={[12, 12]}>
                <Col xs={24} lg={16} xl={17}>
                  <ReactECharts
                    option={plateauHeatmapOption}
                    style={{ height: plateauHeatmapChartHeight, width: '100%' }}
                    onEvents={plateauHeatmapOnEvents}
                  />
                </Col>
                <Col xs={24} lg={8} xl={7}>
                  <Space orientation="vertical" size={10} style={{ width: '100%' }}>
                    <Alert
                      type="info"
                      showIcon
                      title="交互说明"
                      description="点击方块回填参数；框选后可加入候选参数集。橙线表示每个横轴取值下的最优纵轴点。"
                    />
                    <Card size="small" title="热力图设置">
                      <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                        <span>横轴参数</span>
                        <Select
                          value={plateauHeatmapXAxis}
                          options={PLATEAU_AXIS_OPTIONS.filter((item) => item.value !== plateauHeatmapYAxis)}
                          onChange={(value) => setPlateauHeatmapXAxis(value as PlateauAxisKey)}
                          size="small"
                        />
                        <span>纵轴参数</span>
                        <Select
                          value={plateauHeatmapYAxis}
                          options={PLATEAU_AXIS_OPTIONS.filter((item) => item.value !== plateauHeatmapXAxis)}
                          onChange={(value) => setPlateauHeatmapYAxis(value as PlateauAxisKey)}
                          size="small"
                        />
                        <span>颜色映射指标</span>
                        <Select
                          value={plateauHeatmapMetric}
                          options={PLATEAU_METRIC_OPTIONS}
                          onChange={(value) => setPlateauHeatmapMetric(value as PlateauMetricKey)}
                          size="small"
                        />
                        <Space wrap>
                          <Tag color="processing">显示方块值</Tag>
                          <Switch checked={plateauHeatmapShowCellLabel} onChange={setPlateauHeatmapShowCellLabel} />
                        </Space>
                        <Space wrap>
                          <Tag color="orange">最佳点连线</Tag>
                          <Switch checked={plateauHeatmapShowBestPath} onChange={setPlateauHeatmapShowBestPath} />
                        </Space>
                      </Space>
                    </Card>
                    <Card size="small" title="候选参数集">
                      <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                        <Space wrap>
                          <Tag color="blue">{`框选方块: ${plateauBrushSelectedKeys.length}`}</Tag>
                          <Tag color="geekblue">{`候选参数: ${plateauCandidatePoints.length}`}</Tag>
                        </Space>
                        <Space wrap>
                          <Button size="small" disabled={plateauBrushSelectedKeys.length <= 0} onClick={handleAddBrushSelectionToCandidates}>
                            加入候选
                          </Button>
                          <Button
                            size="small"
                            disabled={plateauBrushSelectedKeys.length <= 0}
                            onClick={() => setPlateauBrushSelectedKeys([])}
                          >
                            清空框选
                          </Button>
                        </Space>
                        {plateauCandidateOptions.length > 0 ? (
                          <Select
                            value={plateauCandidatePickRank}
                            options={plateauCandidateOptions}
                            onChange={(value) => setPlateauCandidatePickRank(Number(value))}
                            size="small"
                          />
                        ) : null}
                        <Space wrap>
                          <Button size="small" disabled={!selectedCandidatePoint} onClick={handleApplySelectedCandidatePoint}>
                            回填候选
                          </Button>
                          <Button size="small" disabled={plateauCandidatePoints.length <= 0} onClick={handleClearCandidatePoints}>
                            清空候选
                          </Button>
                        </Space>
                      </Space>
                    </Card>
                  </Space>
                </Col>
              </Row>
            </Card>
          ) : (
            <Alert
              type="info"
              showIcon
              title="热力图暂不可用"
              description={
                plateauHeatmapUnavailableReason
                || '当前参数分布不足以形成二维网格，请扩展参数扫描范围后重试。'
              }
            />
          )}

          <Card title="参数收藏库（本地持久化）">
            <Space orientation="vertical" size={10} style={{ width: '100%' }}>
              <Space wrap>
                <Tag color="geekblue">{`已收藏: ${plateauSavedPresets.length}`}</Tag>
                {plateauSavedPresetOptions.length > 0 ? (
                  <Select
                    style={{ minWidth: 420 }}
                    value={plateauSavedPresetId ?? undefined}
                    options={plateauSavedPresetOptions}
                    onChange={(value) => setPlateauSavedPresetId(String(value))}
                  />
                ) : null}
                <Button disabled={!selectedSavedPreset} onClick={handleApplySavedPreset}>
                  回填收藏参数
                </Button>
                <Button danger disabled={!selectedSavedPreset} onClick={handleDeleteSavedPreset}>
                  删除当前收藏
                </Button>
              </Space>
              <Table
                size="small"
                columns={plateauSavedPresetColumns}
                dataSource={plateauSavedPresets}
                rowKey="id"
                scroll={{ x: 1220 }}
                pagination={{
                  defaultPageSize: 8,
                  pageSizeOptions: [8, 20, 50, 100],
                  showSizeChanger: true,
                  showTotal: (total) => `共 ${total} 条`,
                }}
              />
            </Space>
          </Card>

          <Card title="收益平原结果（按评分排序）">
            <Table
              size="small"
              columns={plateauColumnsWithAction}
              dataSource={plateauTableRows}
              rowKey="__rowKey"
              scroll={{ x: 1460 }}
              pagination={{
                defaultPageSize: 10,
                pageSizeOptions: [10, 20, 50, 100],
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 条`,
              }}
            />
          </Card>

          <Card title="平原运行说明">
            {plateauResult.notes.length === 0 ? (
              <span>无说明。</span>
            ) : (
              <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                {plateauResult.notes.map((note, idx) => (
                  <li key={`${idx}-${note}`}>{note}</li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}

      {effectiveRunError ? <Alert type="error" title={effectiveRunError} showIcon /> : null}

      {taskStatus ? (
        <Card title={taskRunning ? '回测进度' : '最近任务进度'}>
          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
            <Progress
              percent={Math.max(0, Math.min(100, Number(taskProgress?.percent ?? 0)))}
              status={taskRunning ? 'active' : (taskStatus.status === 'succeeded' ? 'success' : 'normal')}
            />
            <div>{taskProgress?.message || '任务执行中...'}</div>
            {taskProgress?.current_date ? (
              <div>当前日期：{taskProgress.current_date}</div>
            ) : (
              <div>当前日期：准备中...</div>
            )}
            <div>
              进度：{taskProgress?.processed_dates ?? 0} / {taskProgress?.total_dates ?? 0}
            </div>
            {taskProgress?.warning ? <Alert type="warning" showIcon title={taskProgress.warning} /> : null}
            {taskStageRows.rows.length > 0 ? (
              <Card size="small" title={`阶段耗时（累计 ${(taskStageRows.totalMs / 1000).toFixed(2)}s）`}>
                <Space orientation="vertical" size={6} style={{ width: '100%' }}>
                  {taskStageRows.rows.map((row) => (
                    <Space key={row.stageKey} wrap style={{ justifyContent: 'space-between', width: '100%' }}>
                      <span>{row.label}</span>
                      <Space wrap size={6}>
                        <Tag color="geekblue">{row.elapsedSecText}</Tag>
                        <Tag>{row.shareText}</Tag>
                      </Space>
                    </Space>
                  ))}
                </Space>
              </Card>
            ) : null}
          </Space>
        </Card>
      ) : null}

      {result ? (
        <>
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="成交笔数" value={result.stats.trade_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="胜率" value={result.stats.win_rate * 100} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="总收益" value={result.stats.total_return * 100} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="最大回撤" value={result.stats.max_drawdown * 100} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="候选信号" value={result.candidate_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="跳过信号" value={result.skipped_count} />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="成交率" value={result.fill_rate * 100} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card>
                <Statistic title="最大并发持仓" value={result.max_concurrent_positions} />
              </Card>
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col xs={24} lg={12}>
              <Card title="资金曲线">
                <ReactECharts option={equityOption} style={{ height: 290 }} />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title="回撤曲线">
                <ReactECharts option={drawdownOption} style={{ height: 290 }} />
              </Card>
            </Col>
          </Row>

          <Card title="运行说明">
            {result.notes.length === 0 ? (
              <span>无说明。</span>
            ) : (
              <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                {result.notes.map((note, idx) => (
                  <li key={`${idx}-${note}`}>{note}</li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="交易明细">
            <Table
              size="small"
              columns={tradeColumns}
              dataSource={result.trades}
              rowKey={(row) => `${row.symbol}-${row.entry_date}-${row.exit_date}-${row.quantity}`}
              scroll={{ x: 1480 }}
              pagination={{
                current: tradePage,
                pageSize: tradePageSize,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 25, 50, 100],
                showTotal: (total) => `共 ${total} 条`,
                onChange: (page, pageSize) => {
                  if (pageSize !== tradePageSize) {
                    setTradePageSize(pageSize)
                    setTradePage(1)
                    return
                  }
                  setTradePage(page)
                },
              }}
            />
          </Card>
        </>
      ) : (
        <Alert type="info" title="暂无回测结果，请先设置参数并点击“开始回测”。" showIcon />
      )}
    </Space>
  )
}

