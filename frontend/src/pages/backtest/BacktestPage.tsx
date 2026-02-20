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
import { getBacktestTask, getLatestScreenerRun, startBacktestTask } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type {
  BacktestPoolRollMode,
  BacktestPriorityMode,
  BacktestResponse,
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
const WY_EVENTS = ['PS', 'SC', 'AR', 'ST', 'TSO', 'Spring', 'SOS', 'JOC', 'LPS', 'UTAD', 'SOW', 'LPSY']
const BACKTEST_DEFAULT_BOARD_FILTERS: BoardFilter[] = ['main', 'gem', 'star']
const ALLOWED_BOARD_FILTERS: BoardFilter[] = ['main', 'gem', 'star', 'beijing', 'st']

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
  const [tradePage, setTradePage] = useState(1)
  const [tradePageSize, setTradePageSize] = useState(initialDraft.trades_page_size)
  const [result, setResult] = useState<BacktestResponse | undefined>(undefined)
  const [runError, setRunError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState('')
  const [taskStatus, setTaskStatus] = useState<BacktestTaskStatusResponse | null>(null)

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
      setTaskId(payload.task_id)
      setTaskStatus(null)
      setRunError(null)
      setResult(undefined)
      message.info('回测任务已提交，正在按日期滚动计算...')
    },
    onError: (error) => {
      const text = formatApiError(error)
      setRunError(text)
      message.error(text)
    },
  })

  const bindLatestRunMutation = useMutation({
    mutationFn: getLatestScreenerRun,
    onSuccess: (detail) => {
      applyRunMeta(detail.run_id, detail.as_of_date?.trim() || undefined)
      message.success(`已带入最新筛选任务：${detail.run_id}`)
    },
    onError: (error) => message.error(formatApiError(error)),
  })

  useEffect(() => {
    setTradePage(1)
  }, [result?.trades])

  useEffect(() => {
    if (!taskId) return
    let active = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      try {
        const status = await getBacktestTask(taskId)
        if (!active) return
        setTaskStatus(status)
        if (status.status === 'succeeded') {
          setResult(status.result ?? undefined)
          setRunError(null)
          setTaskId('')
          return
        }
        if (status.status === 'failed') {
          const text = status.error?.trim() || '回测任务失败'
          setRunError(text)
          message.error(text)
          setTaskId('')
          return
        }
      } catch (error) {
        if (!active) return
        const text = formatApiError(error)
        setRunError(text)
        message.error(text)
        setTaskId('')
        return
      }
      timer = setTimeout(poll, 400)
    }

    void poll()
    return () => {
      active = false
      if (timer) clearTimeout(timer)
    }
  }, [taskId, message])

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
    const payload = {
      mode,
      run_id: runId.trim() || undefined,
      trend_step: trendStep,
      pool_roll_mode: poolRollMode,
      board_filters: shouldApplyBoardFilters ? effectiveBoardFilters : undefined,
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
    setRunError(null)
    startTaskMutation.mutate(payload)
  }

  function handleBindLatestRunId() {
    if (bindLatestRunMutation.isPending) return
    const cached = readScreenerRunMetaFromStorage()
    if (cached?.runId) {
      applyRunMeta(cached.runId, cached.asOfDate)
      if (cached.boardFilters?.length) {
        setBoardFilters(cached.boardFilters)
      }
      message.success(`已从本地筛选缓存带入任务：${cached.runId}`)
      return
    }
    bindLatestRunMutation.mutate()
  }

  const taskRunning = Boolean(taskId) || startTaskMutation.isPending
  const runLoading = taskRunning
  const taskProgress = taskStatus?.progress

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
                <Button loading={bindLatestRunMutation.isPending} onClick={handleBindLatestRunId}>
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
          {result ? <Tag color="green">{`${result.range.date_from} ~ ${result.range.date_to}`}</Tag> : null}
        </Space>
      </Card>

      {runError ? <Alert type="error" title={runError} showIcon /> : null}

      {taskRunning || taskStatus?.status === 'running' || taskStatus?.status === 'pending' ? (
        <Card title="回测进度">
          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
            <Progress percent={Math.max(0, Math.min(100, Number(taskProgress?.percent ?? 0)))} status="active" />
            <div>{taskProgress?.message || '任务执行中...'}</div>
            {taskProgress?.current_date ? (
              <div>当前日期：{taskProgress.current_date}</div>
            ) : (
              <div>当前日期：准备中...</div>
            )}
            <div>
              进度：{taskProgress?.processed_dates ?? 0} / {taskProgress?.total_dates ?? 0}
            </div>
            {taskProgress?.warning ? <Alert type="warning" showIcon message={taskProgress.warning} /> : null}
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

