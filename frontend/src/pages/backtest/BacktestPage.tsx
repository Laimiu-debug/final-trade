import { useEffect, useMemo, useRef, useState } from 'react'
import dayjs, { Dayjs } from 'dayjs'
import { useMutation, useQuery } from '@tanstack/react-query'
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
import * as XLSX from 'xlsx'
import { ApiError } from '@/shared/api/client'
import {
  buildBacktestReportPackage,
  cancelBacktestPlateauTask,
  cancelBacktestTask,
  deleteBacktestReport,
  getBacktestReport,
  getStrategies,
  importBacktestReportPackage,
  listBacktestReports,
  pauseBacktestPlateauTask,
  pauseBacktestTask,
  resumeBacktestPlateauTask,
  resumeBacktestTask,
  runBacktestABExperiment,
  startBacktestPlateauTask,
  startBacktestTask,
} from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import { useBacktestPlateauTaskStore } from '@/state/backtestPlateauTaskStore'
import { useBacktestTaskStore } from '@/state/backtestTaskStore'
import {
  buildStrategyParamsPayload,
  deleteSharedStrategyPreset,
  getSharedLastStrategyId,
  getSharedStrategyParams,
  listSharedStrategyPresets,
  normalizeStrategyParams,
  parseStrategyParamSchema,
  resolveDefaultStrategyId,
  saveSharedStrategyPreset,
  setSharedStrategyParams,
} from '@/shared/utils/strategyParams'
import type { StrategyParamPreset, StrategyParamSpec } from '@/shared/utils/strategyParams'
import type {
  BacktestABComparisonRow,
  BacktestABExperimentResponse,
  BacktestABVariantConfig,
  BacktestABVariantResult,
  BacktestPlateauCorrelationRow,
  BacktestPlateauPoint,
  BacktestPlateauResponse,
  BacktestPlateauTaskStatusResponse,
  BacktestPoolRollMode,
  BacktestPriorityMode,
  BacktestMonteCarloSummary,
  BacktestRegimeBucket,
  BacktestReportSummary,
  BacktestResponse,
  BacktestRunRequest,
  BacktestStabilityDiagnostics,
  BacktestTaskStatusResponse,
  BacktestTrade,
  BacktestWalkForwardReport,
  BoardFilter,
  SignalScanMode,
  StrategyId,
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
  entryDelayDays: 1,
  delayInvalidationEnabled: true,
  maxSymbols: 120,
  enableAdvancedAnalysis: true,
  defaultLookbackDays: 180,
}

const SCREENER_CACHE_KEY = 'tdx-trend-screener-cache-v4'
const BACKTEST_FORM_CACHE_KEY = 'tdx-trend-backtest-form-v2'
const BACKTEST_PLATEAU_FORM_CACHE_KEY = 'tdx-trend-backtest-plateau-form-v1'
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
  strategy_id: StrategyId
  strategy_params: Record<string, unknown>
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
  entry_delay_days: number
  delay_invalidation_enabled: boolean
  max_symbols: number
  enable_advanced_analysis: boolean
  trades_page_size: number
}

type BacktestPlateauFormDraft = {
  sampling_mode: 'grid' | 'lhs'
  sample_points: number
  random_seed: number | null
  window_days_list_raw: string
  min_score_list_raw: string
  stop_loss_pct_list_raw: string
  take_profit_pct_list_raw: string
  max_positions_list_raw: string
  position_pct_list_raw: string
  max_symbols_list_raw: string
  topk_list_raw: string
  heatmap_x_axis: PlateauAxisKey
  heatmap_y_axis: PlateauAxisKey
  heatmap_metric: PlateauMetricKey
  heatmap_show_best_path: boolean
  heatmap_show_cell_label: boolean
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

function bufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  const chunkSize = 0x8000
  let out = ''
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, Math.min(bytes.length, offset + chunkSize))
    out += String.fromCharCode(...Array.from(chunk))
  }
  return btoa(out)
}

function base64ToUint8Array(raw: string): Uint8Array {
  const text = String(raw || '').trim()
  const binary = atob(text)
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i)
  }
  return out
}

function downloadBlob(fileName: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function escapeHtml(raw: string): string {
  return String(raw || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function formatSigned(value: number): string {
  const numeric = Number(value || 0)
  const sign = numeric >= 0 ? '+' : ''
  return `${sign}${numeric.toFixed(3)}`
}

function classifyCorrelationDirection(value: number): '正相关' | '负相关' | '弱相关' {
  if (value > 0.05) return '正相关'
  if (value < -0.05) return '负相关'
  return '弱相关'
}

function correlationDirectionTagColor(direction: '正相关' | '负相关' | '弱相关'): string {
  if (direction === '正相关') return 'success'
  if (direction === '负相关') return 'error'
  return 'default'
}

function safePearsonCorrelation(xValues: number[], yValues: number[]): number {
  const count = Math.min(xValues.length, yValues.length)
  if (count < 2) return 0
  const xs = xValues.slice(0, count).map((item) => Number(item))
  const ys = yValues.slice(0, count).map((item) => Number(item))
  const meanX = xs.reduce((sum, value) => sum + value, 0) / count
  const meanY = ys.reduce((sum, value) => sum + value, 0) / count
  const varX = xs.reduce((sum, value) => sum + (value - meanX) ** 2, 0)
  const varY = ys.reduce((sum, value) => sum + (value - meanY) ** 2, 0)
  if (varX <= 1e-12 || varY <= 1e-12) return 0
  const cov = xs.reduce((sum, value, index) => sum + (value - meanX) * (ys[index]! - meanY), 0)
  const corr = cov / Math.sqrt(varX * varY)
  if (!Number.isFinite(corr)) return 0
  return Math.max(-1, Math.min(1, corr))
}

function buildPlateauCorrelationsFromPoints(points: BacktestPlateauPoint[]): BacktestPlateauCorrelationRow[] {
  if (points.length < 2) return []
  const scoreValues = points.map((row) => Number(row.score))
  const totalReturnValues = points.map((row) => Number(row.stats.total_return))
  const winRateValues = points.map((row) => Number(row.stats.win_rate))
  const specs: Array<{
    key: string
    label: string
    pick: (row: BacktestPlateauPoint) => number
  }> = [
    { key: 'window_days', label: '信号窗口天数', pick: (row) => Number(row.params.window_days) },
    { key: 'min_score', label: '最低评分', pick: (row) => Number(row.params.min_score) },
    { key: 'stop_loss', label: '止损比例', pick: (row) => Number(row.params.stop_loss) },
    { key: 'take_profit', label: '止盈比例', pick: (row) => Number(row.params.take_profit) },
    { key: 'max_positions', label: '最大并发持仓', pick: (row) => Number(row.params.max_positions) },
    { key: 'position_pct', label: '单笔仓位占比', pick: (row) => Number(row.params.position_pct) },
    { key: 'max_symbols', label: '最大股票数', pick: (row) => Number(row.params.max_symbols) },
    { key: 'priority_topk_per_day', label: '同日TopK', pick: (row) => Number(row.params.priority_topk_per_day) },
  ]
  const rows = specs.map((item) => {
    const xValues = points.map(item.pick)
    return {
      parameter: item.key,
      parameter_label: item.label,
      score_corr: Number(safePearsonCorrelation(xValues, scoreValues).toFixed(6)),
      total_return_corr: Number(safePearsonCorrelation(xValues, totalReturnValues).toFixed(6)),
      win_rate_corr: Number(safePearsonCorrelation(xValues, winRateValues).toFixed(6)),
    } as BacktestPlateauCorrelationRow
  })
  rows.sort((left, right) => {
    const leftStrength = Math.max(Math.abs(left.score_corr), Math.abs(left.total_return_corr), Math.abs(left.win_rate_corr))
    const rightStrength = Math.max(Math.abs(right.score_corr), Math.abs(right.total_return_corr), Math.abs(right.win_rate_corr))
    return rightStrength - leftStrength
  })
  return rows
}

function resolvePlateauCorrelations(plateauResult?: BacktestPlateauResponse | null): BacktestPlateauCorrelationRow[] {
  if (!plateauResult) return []
  const existingRows = Array.isArray(plateauResult.correlations) ? plateauResult.correlations : []
  if (existingRows.length > 0) {
    return existingRows
  }
  const validPoints = (plateauResult.points ?? []).filter((row) => !row.error)
  return buildPlateauCorrelationsFromPoints(validPoints)
}

function buildBacktestReportWorkbookBuffer(
  runRequest: BacktestRunRequest,
  runResult: BacktestResponse,
  plateauResult?: BacktestPlateauResponse | null,
): ArrayBuffer {
  const workbook = XLSX.utils.book_new()
  const plateauCorrelations = resolvePlateauCorrelations(plateauResult)
  const plateauBestPoint = plateauResult?.best_point ?? null
  const riskMetrics = runResult.risk_metrics ?? null
  const stability = runResult.stability_diagnostics ?? null
  const regimeBreakdown = runResult.regime_breakdown ?? []
  const monteCarlo = runResult.monte_carlo ?? null
  const walkForward = runResult.walk_forward ?? null
  const summaryRows = [
    {
      date_from: runResult.range.date_from,
      date_to: runResult.range.date_to,
      mode: runRequest.mode,
      pool_roll_mode: runRequest.pool_roll_mode,
      trade_count: runResult.stats.trade_count,
      win_count: runResult.stats.win_count,
      loss_count: runResult.stats.loss_count,
      win_rate: runResult.stats.win_rate,
      total_return: runResult.stats.total_return,
      max_drawdown: runResult.stats.max_drawdown,
      avg_pnl_ratio: runResult.stats.avg_pnl_ratio,
      profit_factor: runResult.stats.profit_factor,
      candidate_count: runResult.candidate_count,
      skipped_count: runResult.skipped_count,
      fill_rate: runResult.fill_rate,
      max_concurrent_positions: runResult.max_concurrent_positions,
      has_plateau_result: Boolean(plateauResult),
      plateau_total_combinations: plateauResult?.total_combinations ?? null,
      plateau_evaluated_combinations: plateauResult?.evaluated_combinations ?? null,
      plateau_best_score: plateauBestPoint?.score ?? null,
      plateau_best_total_return: plateauBestPoint?.stats.total_return ?? null,
      plateau_best_win_rate: plateauBestPoint?.stats.win_rate ?? null,
      sharpe: riskMetrics?.sharpe ?? null,
      sortino: riskMetrics?.sortino ?? null,
      calmar: riskMetrics?.calmar ?? null,
      expectancy: riskMetrics?.expectancy ?? null,
      stability_score: stability?.stability_score ?? null,
      monte_carlo_ruin_probability: monteCarlo?.ruin_probability ?? null,
      walk_forward_oos_pass_rate: walkForward?.oos_pass_rate ?? null,
    },
  ]
  const paramRows = [runRequest]
  const noteRows = runResult.notes.map((item, index) => ({ index: index + 1, note: item }))
  const tradeRows = runResult.trades.map((row) => {
    const parsedExit = parseExitReason(row.exit_reason)
    return {
      ...row,
      entry_signal: formatEventSequence(row.entry_signal),
      exit_reason: parsedExit.detail ? `${parsedExit.label}:${parsedExit.detail}` : parsedExit.label,
    }
  })
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(summaryRows), 'Summary')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(paramRows), 'Params')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(tradeRows), 'Trades')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(runResult.equity_curve), 'Equity')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(runResult.drawdown_curve), 'Drawdown')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(runResult.monthly_returns), 'Monthly')
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(noteRows), 'Notes')
  if (riskMetrics) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet([riskMetrics]), 'RiskMetrics')
  }
  if (stability) {
    const stabilityRows = [
      {
        stability_score: stability.stability_score,
        min_trade_count_threshold: stability.min_trade_count_threshold,
        trade_count_penalty: stability.trade_count_penalty,
        neighborhood_consistency: stability.neighborhood_consistency,
        return_variance_penalty: stability.return_variance_penalty,
        monthly_return_std: stability.monthly_return_std,
      },
    ]
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(stabilityRows), 'Stability')
    if (stability.notes.length > 0) {
      XLSX.utils.book_append_sheet(
        workbook,
        XLSX.utils.json_to_sheet(stability.notes.map((note, index) => ({ index: index + 1, note }))),
        'StabilityNotes',
      )
    }
  }
  if (regimeBreakdown.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(regimeBreakdown), 'Regimes')
  }
  if (monteCarlo) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet([monteCarlo]), 'MonteCarlo')
  }
  if (walkForward) {
    const walkSummary = [
      {
        fold_count: walkForward.fold_count,
        candidate_count: walkForward.candidate_count,
        oos_pass_rate: walkForward.oos_pass_rate,
        avg_test_return: walkForward.avg_test_return,
        avg_test_win_rate: walkForward.avg_test_win_rate,
      },
    ]
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(walkSummary), 'WalkForward')
    if (walkForward.folds.length > 0) {
      const walkFoldRows = walkForward.folds.map((fold) => ({
        fold_index: fold.fold_index,
        train_date_from: fold.train_date_from,
        train_date_to: fold.train_date_to,
        test_date_from: fold.test_date_from,
        test_date_to: fold.test_date_to,
        train_score: fold.train_score,
        test_score: fold.test_score,
        train_total_return: fold.train_stats.total_return,
        train_win_rate: fold.train_stats.win_rate,
        test_total_return: fold.test_stats.total_return,
        test_win_rate: fold.test_stats.win_rate,
        window_days: fold.selected_params.window_days,
        min_score: fold.selected_params.min_score,
        stop_loss: fold.selected_params.stop_loss,
        take_profit: fold.selected_params.take_profit,
        max_positions: fold.selected_params.max_positions,
        position_pct: fold.selected_params.position_pct,
        max_symbols: fold.selected_params.max_symbols,
        priority_topk_per_day: fold.selected_params.priority_topk_per_day,
      }))
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(walkFoldRows), 'WalkForwardFolds')
    }
    if (walkForward.notes.length > 0) {
      XLSX.utils.book_append_sheet(
        workbook,
        XLSX.utils.json_to_sheet(walkForward.notes.map((note, index) => ({ index: index + 1, note }))),
        'WalkForwardNotes',
      )
    }
  }
  if (plateauResult) {
    const plateauSummaryRows = [
      {
        total_combinations: plateauResult.total_combinations,
        evaluated_combinations: plateauResult.evaluated_combinations,
        generated_at: plateauResult.generated_at,
        best_score: plateauBestPoint?.score ?? null,
        best_total_return: plateauBestPoint?.stats.total_return ?? null,
        best_win_rate: plateauBestPoint?.stats.win_rate ?? null,
      },
    ]
    const plateauPointRows = (plateauResult.points ?? []).map((row, index) => ({
      rank: index + 1,
      score: row.score,
      total_return: row.stats.total_return,
      max_drawdown: row.stats.max_drawdown,
      win_rate: row.stats.win_rate,
      trade_count: row.stats.trade_count,
      window_days: row.params.window_days,
      min_score: row.params.min_score,
      stop_loss: row.params.stop_loss,
      take_profit: row.params.take_profit,
      max_positions: row.params.max_positions,
      position_pct: row.params.position_pct,
      max_symbols: row.params.max_symbols,
      priority_topk_per_day: row.params.priority_topk_per_day,
      candidate_count: row.candidate_count,
      skipped_count: row.skipped_count,
      fill_rate: row.fill_rate,
      max_concurrent_positions: row.max_concurrent_positions,
      cache_hit: row.cache_hit,
      error: row.error ?? '',
    }))
    const plateauCorrelationRows = plateauCorrelations.map((item) => ({
      parameter: item.parameter,
      parameter_label: item.parameter_label,
      score_corr: item.score_corr,
      score_direction: classifyCorrelationDirection(item.score_corr),
      total_return_corr: item.total_return_corr,
      total_return_direction: classifyCorrelationDirection(item.total_return_corr),
      win_rate_corr: item.win_rate_corr,
      win_rate_direction: classifyCorrelationDirection(item.win_rate_corr),
    }))
    const plateauNoteRows = (plateauResult.notes ?? []).map((item, index) => ({ index: index + 1, note: item }))
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(plateauSummaryRows), 'Plateau')
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(plateauPointRows), 'PlateauPoints')
    if (plateauCorrelationRows.length > 0) {
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(plateauCorrelationRows), 'PlateauCorr')
    }
    if (plateauNoteRows.length > 0) {
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(plateauNoteRows), 'PlateauNotes')
    }
  }
  return XLSX.write(workbook, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer
}

function buildBacktestReportHtml(
  runRequest: BacktestRunRequest,
  runResult: BacktestResponse,
  plateauResult?: BacktestPlateauResponse | null,
): string {
  const rows = runResult.trades
    .map((trade) => {
      const parsedExit = parseExitReason(trade.exit_reason)
      const exitDisplay = parsedExit.detail ? `${parsedExit.label}:${parsedExit.detail}` : parsedExit.label
      return `<tr>
        <td>${escapeHtml(trade.symbol)}</td>
        <td>${escapeHtml(trade.name)}</td>
        <td>${escapeHtml(trade.signal_date)}</td>
        <td>${escapeHtml(trade.entry_date)}</td>
        <td>${escapeHtml(trade.exit_date)}</td>
        <td>${escapeHtml(formatEventSequence(trade.entry_signal))}</td>
        <td>${escapeHtml(exitDisplay)}</td>
        <td>${trade.quantity}</td>
        <td>${trade.entry_price}</td>
        <td>${trade.exit_price}</td>
        <td>${trade.holding_days}</td>
        <td>${trade.pnl_amount}</td>
        <td>${trade.pnl_ratio}</td>
      </tr>`
    })
    .join('\n')
  const noteList = runResult.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('\n')
  const plateauCorrelations = resolvePlateauCorrelations(plateauResult)
  const plateauValidPoints = (plateauResult?.points ?? []).filter((row) => !row.error)
  const plateauPointRows = plateauValidPoints
    .slice(0, 100)
    .map((row, index) => (
      `<tr>
        <td>${index + 1}</td>
        <td>${row.score.toFixed(3)}</td>
        <td>${(Number(row.stats.total_return) * 100).toFixed(2)}%</td>
        <td>${(Number(row.stats.win_rate) * 100).toFixed(2)}%</td>
        <td>${row.params.window_days}</td>
        <td>${Number(row.params.min_score).toFixed(2)}</td>
        <td>${(Number(row.params.stop_loss) * 100).toFixed(2)}%</td>
        <td>${(Number(row.params.take_profit) * 100).toFixed(2)}%</td>
      </tr>`
    ))
    .join('\n')
  const plateauCorrelationRows = plateauCorrelations
    .map((item) => (
      `<tr>
        <td>${escapeHtml(item.parameter_label)}</td>
        <td>${formatSigned(item.score_corr)} (${classifyCorrelationDirection(item.score_corr)})</td>
        <td>${formatSigned(item.total_return_corr)} (${classifyCorrelationDirection(item.total_return_corr)})</td>
        <td>${formatSigned(item.win_rate_corr)} (${classifyCorrelationDirection(item.win_rate_corr)})</td>
      </tr>`
    ))
    .join('\n')
  const plateauNoteList = (plateauResult?.notes ?? []).map((note) => `<li>${escapeHtml(note)}</li>`).join('\n')
  const riskMetrics = runResult.risk_metrics ?? null
  const stability = runResult.stability_diagnostics ?? null
  const regimeRows = (runResult.regime_breakdown ?? [])
    .map((item) => (
      `<tr>
        <td>${escapeHtml(item.label)}</td>
        <td>${item.trade_count}</td>
        <td>${(Number(item.win_rate) * 100).toFixed(2)}%</td>
        <td>${(Number(item.total_return) * 100).toFixed(2)}%</td>
        <td>${(Number(item.avg_pnl_ratio) * 100).toFixed(2)}%</td>
        <td>${(Number(item.max_drawdown) * 100).toFixed(2)}%</td>
      </tr>`
    ))
    .join('\n')
  const monteCarlo = runResult.monte_carlo ?? null
  const walkForward = runResult.walk_forward ?? null
  const walkForwardRows = (walkForward?.folds ?? [])
    .map((fold) => (
      `<tr>
        <td>${fold.fold_index}</td>
        <td>${escapeHtml(fold.train_date_from)}~${escapeHtml(fold.train_date_to)}</td>
        <td>${escapeHtml(fold.test_date_from)}~${escapeHtml(fold.test_date_to)}</td>
        <td>${formatSigned(fold.train_score)}</td>
        <td>${formatSigned(fold.test_score)}</td>
        <td>${(Number(fold.test_stats.total_return) * 100).toFixed(2)}%</td>
        <td>${(Number(fold.test_stats.win_rate) * 100).toFixed(2)}%</td>
      </tr>`
    ))
    .join('\n')
  const walkForwardNotes = (walkForward?.notes ?? []).map((note) => `<li>${escapeHtml(note)}</li>`).join('\n')
  const generatedAt = dayjs().format('YYYY-MM-DD HH:mm:ss')
  const advancedSection = `
  <h2>高级分析</h2>
  ${riskMetrics
    ? `<div class="meta">
    <div>Sharpe：${Number(riskMetrics.sharpe).toFixed(3)}</div>
    <div>Sortino：${Number(riskMetrics.sortino).toFixed(3)}</div>
    <div>Calmar：${Number(riskMetrics.calmar).toFixed(3)}</div>
    <div>Expectancy：${(Number(riskMetrics.expectancy) * 100).toFixed(2)}%</div>
    <div>最大连续亏损：${riskMetrics.max_consecutive_losses}</div>
    <div>回撤恢复天数：${riskMetrics.recovery_days}</div>
  </div>`
    : '<div>无风险指标。</div>'}
  ${stability
    ? `<h2>稳定性评分</h2>
  <div class="meta">
    <div>稳定性评分：${Number(stability.stability_score).toFixed(3)}</div>
    <div>邻域一致性：${Number(stability.neighborhood_consistency).toFixed(3)}</div>
    <div>交易数惩罚：${Number(stability.trade_count_penalty).toFixed(3)}</div>
    <div>方差惩罚：${Number(stability.return_variance_penalty).toFixed(3)}</div>
    <div>月度收益标准差：${Number(stability.monthly_return_std).toFixed(4)}</div>
  </div>`
    : ''}
  ${(stability?.notes?.length ?? 0) > 0 ? `<ul>${(stability?.notes ?? []).map((note) => `<li>${escapeHtml(note)}</li>`).join('\n')}</ul>` : ''}
  <h2>状态拆分（代理）</h2>
  ${regimeRows
    ? `<table>
    <thead>
      <tr>
        <th>状态</th><th>交易数</th><th>胜率</th><th>总收益</th><th>平均单笔</th><th>最大回撤</th>
      </tr>
    </thead>
    <tbody>${regimeRows}</tbody>
  </table>`
    : '<div>无状态拆分数据。</div>'}
  <h2>蒙特卡洛压力测试</h2>
  ${monteCarlo
    ? `<div class="meta">
    <div>模拟次数：${monteCarlo.simulations}</div>
    <div>收益 P5/P50/P95：${(Number(monteCarlo.total_return_p5) * 100).toFixed(2)}% / ${(Number(monteCarlo.total_return_p50) * 100).toFixed(2)}% / ${(Number(monteCarlo.total_return_p95) * 100).toFixed(2)}%</div>
    <div>回撤 P5/P50/P95：${(Number(monteCarlo.max_drawdown_p5) * 100).toFixed(2)}% / ${(Number(monteCarlo.max_drawdown_p50) * 100).toFixed(2)}% / ${(Number(monteCarlo.max_drawdown_p95) * 100).toFixed(2)}%</div>
    <div>极端亏损概率：${(Number(monteCarlo.ruin_probability) * 100).toFixed(2)}%</div>
  </div>`
    : '<div>无蒙特卡洛数据。</div>'}
  <h2>Walk-forward</h2>
  ${walkForward
    ? `<div class="meta">
    <div>折叠数：${walkForward.fold_count}</div>
    <div>候选参数数：${walkForward.candidate_count}</div>
    <div>OOS 通过率：${(Number(walkForward.oos_pass_rate) * 100).toFixed(2)}%</div>
    <div>测试平均收益：${(Number(walkForward.avg_test_return) * 100).toFixed(2)}%</div>
    <div>测试平均胜率：${(Number(walkForward.avg_test_win_rate) * 100).toFixed(2)}%</div>
  </div>`
    : '<div>无 walk-forward 数据。</div>'}
  ${walkForwardRows
    ? `<table>
    <thead>
      <tr>
        <th>fold</th><th>train</th><th>test</th><th>train_score</th><th>test_score</th><th>test_return</th><th>test_win_rate</th>
      </tr>
    </thead>
    <tbody>${walkForwardRows}</tbody>
  </table>`
    : ''}
  ${(walkForward?.notes?.length ?? 0) > 0 ? `<ul>${walkForwardNotes || '<li>无</li>'}</ul>` : ''}`
  const plateauSection = plateauResult
    ? `
  <h2>收益平原概览</h2>
  <div class="meta">
    <div>总组合：${plateauResult.total_combinations}</div>
    <div>评估组数：${plateauResult.evaluated_combinations}</div>
    <div>最佳评分：${plateauResult.best_point ? plateauResult.best_point.score.toFixed(3) : '--'}</div>
    <div>最佳收益：${plateauResult.best_point ? `${(Number(plateauResult.best_point.stats.total_return) * 100).toFixed(2)}%` : '--'}</div>
    <div>最佳胜率：${plateauResult.best_point ? `${(Number(plateauResult.best_point.stats.win_rate) * 100).toFixed(2)}%` : '--'}</div>
    <div>生成时间：${escapeHtml(plateauResult.generated_at)}</div>
  </div>
  <h2>参数相关性分析</h2>
  ${plateauCorrelationRows
    ? `<table>
    <thead>
      <tr>
        <th>参数</th><th>与评分相关</th><th>与收益相关</th><th>与胜率相关</th>
      </tr>
    </thead>
    <tbody>${plateauCorrelationRows}</tbody>
  </table>`
    : '<div>有效参数组不足，暂无相关性分析。</div>'}
  <h2>收益平原说明</h2>
  <ul>${plateauNoteList || '<li>无</li>'}</ul>
  <h2>收益平原Top100（成功参数）</h2>
  <table>
    <thead>
      <tr>
        <th>rank</th><th>score</th><th>total_return</th><th>win_rate</th><th>window_days</th>
        <th>min_score</th><th>stop_loss</th><th>take_profit</th>
      </tr>
    </thead>
    <tbody>${plateauPointRows || '<tr><td colspan="8">无</td></tr>'}</tbody>
  </table>
  <div class="block">注：仅展示成功参数的前100名，完整数据见 report.xlsx 的 PlateauPoints 工作表。</div>`
    : ''
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Backtest Report ${escapeHtml(runResult.range.date_from)} - ${escapeHtml(runResult.range.date_to)}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; margin: 24px; color: #0f172a; }
    h1, h2 { margin: 8px 0; }
    .meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px 16px; margin-bottom: 16px; }
    .block { margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }
    th { background: #f8fafc; }
  </style>
</head>
<body>
  <h1>策略回测报告</h1>
  <div class="block">生成时间：${escapeHtml(generatedAt)}</div>
  <div class="meta">
    <div>区间：${escapeHtml(runResult.range.date_from)} ~ ${escapeHtml(runResult.range.date_to)}</div>
    <div>模式：${escapeHtml(runRequest.mode)} / ${escapeHtml(runRequest.pool_roll_mode)}</div>
    <div>交易数：${runResult.stats.trade_count}</div>
    <div>胜率：${runResult.stats.win_rate}</div>
    <div>总收益：${runResult.stats.total_return}</div>
    <div>最大回撤：${runResult.stats.max_drawdown}</div>
    <div>成交率：${runResult.fill_rate}</div>
    <div>候选信号：${runResult.candidate_count}</div>
  </div>
  <h2>运行说明</h2>
  <ul>${noteList || '<li>无</li>'}</ul>
  ${advancedSection}
  ${plateauSection}
  <h2>交易明细</h2>
  <table>
    <thead>
      <tr>
        <th>symbol</th><th>name</th><th>signal_date</th><th>entry_date</th><th>exit_date</th>
        <th>entry_signal</th><th>exit_reason</th><th>quantity</th><th>entry_price</th><th>exit_price</th>
        <th>holding_days</th><th>pnl_amount</th><th>pnl_ratio</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</body>
</html>`
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
    strategy_id: 'wyckoff_trend_v1',
    strategy_params: {},
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
    entry_delay_days: TRADE_BACKTEST_DEFAULTS.entryDelayDays,
    delay_invalidation_enabled: TRADE_BACKTEST_DEFAULTS.delayInvalidationEnabled,
    max_symbols: TRADE_BACKTEST_DEFAULTS.maxSymbols,
    enable_advanced_analysis: TRADE_BACKTEST_DEFAULTS.enableAdvancedAnalysis,
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
    merged.strategy_id = merged.strategy_id === 'wyckoff_trend_v2' ? 'wyckoff_trend_v2' : 'wyckoff_trend_v1'
    merged.strategy_params = normalizeStrategyParams(merged.strategy_params)
    if (!['daily', 'weekly', 'position'].includes(String(merged.pool_roll_mode))) {
      merged.pool_roll_mode = defaults.pool_roll_mode
    }
    if (!Number.isFinite(merged.entry_delay_days)) {
      merged.entry_delay_days = defaults.entry_delay_days
    } else {
      merged.entry_delay_days = Math.max(1, Math.min(5, Math.round(Number(merged.entry_delay_days))))
    }
    merged.delay_invalidation_enabled = merged.delay_invalidation_enabled !== false
    merged.enable_advanced_analysis = merged.enable_advanced_analysis !== false
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

function buildDefaultPlateauDraft(): BacktestPlateauFormDraft {
  return {
    sampling_mode: 'lhs',
    sample_points: 120,
    random_seed: 20260221,
    window_days_list_raw: '',
    min_score_list_raw: '',
    stop_loss_pct_list_raw: '',
    take_profit_pct_list_raw: '',
    max_positions_list_raw: '',
    position_pct_list_raw: '',
    max_symbols_list_raw: '',
    topk_list_raw: '',
    heatmap_x_axis: 'window_days',
    heatmap_y_axis: 'min_score',
    heatmap_metric: 'score',
    heatmap_show_best_path: true,
    heatmap_show_cell_label: false,
  }
}

function loadBacktestPlateauDraft(): BacktestPlateauFormDraft {
  const defaults = buildDefaultPlateauDraft()
  if (typeof window === 'undefined') return defaults
  try {
    const raw = window.localStorage.getItem(BACKTEST_PLATEAU_FORM_CACHE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<BacktestPlateauFormDraft>
    const merged = { ...defaults, ...parsed }
    if (!['grid', 'lhs'].includes(String(merged.sampling_mode))) merged.sampling_mode = defaults.sampling_mode
    if (!Number.isFinite(merged.sample_points) || Number(merged.sample_points) <= 0) merged.sample_points = defaults.sample_points
    const randomSeedRaw = merged.random_seed
    merged.random_seed = randomSeedRaw === null ? null : (Number.isFinite(Number(randomSeedRaw)) ? Number(randomSeedRaw) : defaults.random_seed)
    if (!PLATEAU_AXIS_OPTIONS.some((item) => item.value === merged.heatmap_x_axis)) merged.heatmap_x_axis = defaults.heatmap_x_axis
    if (!PLATEAU_AXIS_OPTIONS.some((item) => item.value === merged.heatmap_y_axis)) merged.heatmap_y_axis = defaults.heatmap_y_axis
    if (!PLATEAU_METRIC_OPTIONS.some((item) => item.value === merged.heatmap_metric)) merged.heatmap_metric = defaults.heatmap_metric
    merged.heatmap_show_best_path = Boolean(merged.heatmap_show_best_path)
    merged.heatmap_show_cell_label = Boolean(merged.heatmap_show_cell_label)
    return merged
  } catch {
    return defaults
  }
}

function persistBacktestPlateauDraft(draft: BacktestPlateauFormDraft) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(BACKTEST_PLATEAU_FORM_CACHE_KEY, JSON.stringify(draft))
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

type AnalysisAdvice = {
  level: 'success' | 'warning' | 'error' | 'info'
  title: string
  tips: string[]
}

function normalizeEventToken(raw: string): string {
  const token = String(raw || '').trim()
  if (!token) return ''
  const mapped = {
    M5: 'SOS',
    M6: 'LPS',
    MATRIX: '矩阵入场',
    MATRIX_SELL: '矩阵卖出',
  }[token]
  return mapped || token
}

function formatEventSequence(raw: string): string {
  const text = String(raw || '').trim()
  if (!text) return ''
  const parts = text
    .split('/')
    .map((item) => normalizeEventToken(item))
    .filter(Boolean)
  if (parts.length <= 0) return text
  return parts.join(' / ')
}

function parseExitReason(value: string): ExitReasonView {
  const text = String(value || '').trim()
  if (text.startsWith('event_exit')) {
    const detail = text.includes(':') ? text.split(':').slice(1).join(':').trim() : ''
    const detailText = formatEventSequence(detail)
    return { label: '事件', color: 'blue', detail: detailText || undefined }
  }
  if (text === 'stop_loss') return { label: '止损', color: 'red' }
  if (text === 'take_profit') return { label: '止盈', color: 'green' }
  if (text === 'time_exit') return { label: '超时', color: 'gold' }
  if (text === 'eod_exit') return { label: '收盘', color: 'purple' }
  if (!text) return { label: '未知' }
  return { label: text }
}

function buildStabilityAdvice(stability: BacktestStabilityDiagnostics | null): AnalysisAdvice | null {
  if (!stability) return null
  const score = Number(stability.stability_score || 0)
  const neighborhood = Number(stability.neighborhood_consistency || 0)
  const variancePenalty = Number(stability.return_variance_penalty || 0)
  const tradePenalty = Number(stability.trade_count_penalty || 0)
  if (score >= 0.78 && neighborhood >= 0.6 && variancePenalty <= 0.15) {
    return {
      level: 'success',
      title: '稳定性较好：参数在邻域变化下仍保持一致，当前组合更适合继续验证。',
      tips: [
        '先做小样本实盘/模拟跟踪，确认滑点和手续费后再放大仓位。',
        '保持参数微调幅度，避免一次性大改导致策略漂移。',
      ],
    }
  }
  if (score >= 0.6) {
    const tips = [
      '参数可用但仍偏敏感，建议先控制仓位并观察至少 1~2 个月。',
    ]
    if (variancePenalty >= 0.18) {
      tips.push('方差惩罚较高：优先收敛止盈止损、降低单笔仓位和并发持仓。')
    }
    if (neighborhood < 0.5) {
      tips.push('邻域一致性偏弱：在收益平原中选择更“平台区”的参数，少选尖峰点。')
    }
    if (tradePenalty > 0) {
      tips.push('交易样本偏少：扩展回测区间或放宽筛选条件，先提升样本量再定参数。')
    }
    return {
      level: 'warning',
      title: '稳定性中等：可用，但参数和行情切换时可能出现性能波动。',
      tips,
    }
  }
  return {
    level: 'error',
    title: '稳定性偏弱：当前参数对市场或参数扰动较敏感，实盘容易形变。',
    tips: [
      '优先在收益平原里选择胜率更高、回撤更低的“钝化参数”。',
      '降低仓位与并发持仓，先把极端亏损控制住，再追求收益。',
      '缩短单次持仓周期或收紧出场，减少尾部波动对净值的冲击。',
    ],
  }
}

function buildRegimeAdvice(regimes: BacktestRegimeBucket[]): AnalysisAdvice | null {
  if (!Array.isArray(regimes) || regimes.length <= 0) return null
  const totalTrades = regimes.reduce((sum, row) => sum + Number(row.trade_count || 0), 0)
  if (totalTrades <= 0) {
    return {
      level: 'info',
      title: '市场状态拆分暂无交易样本，暂时无法判断策略在不同环境下的适配性。',
      tips: ['补充样本后再观察牛/震荡/熊三类状态的收益差异。'],
    }
  }
  const dominant = [...regimes].sort((a, b) => Number(b.trade_count || 0) - Number(a.trade_count || 0))[0]!
  const dominantShare = Number(dominant.trade_count || 0) / totalTrades
  const bull = regimes.find((row) => row.regime === 'bull')
  const bear = regimes.find((row) => row.regime === 'bear')
  const allNonPositive = regimes.every((row) => Number(row.total_return || 0) <= 0)
  if (allNonPositive) {
    return {
      level: 'error',
      title: '三种市场状态下收益均不理想，策略当前缺乏可交易优势。',
      tips: [
        '先回到信号层重审入场条件，提升入场质量分阈值。',
        '减少参数自由度，避免过拟合后在所有状态都失效。',
      ],
    }
  }
  if (dominant.regime === 'bear' && dominantShare >= 0.45 && Number(dominant.total_return || 0) < 0) {
    return {
      level: 'warning',
      title: '交易主要集中在熊市代理且表现偏弱，回撤压力会显著放大。',
      tips: [
        '加入趋势过滤或市场风险开关，在弱势状态下降低出手频率。',
        '优先提高止损纪律，减少逆势持仓时间。',
      ],
    }
  }
  if ((bull?.total_return ?? 0) > 0 && (bear?.total_return ?? 0) < 0) {
    return {
      level: 'warning',
      title: '策略呈现“顺势有效、逆势偏弱”特征，择时过滤会明显提升稳定性。',
      tips: [
        '在熊市代理阶段降低仓位上限或直接切换防守参数。',
        '针对震荡/熊市单独做参数组，避免同一套参数全时段硬跑。',
      ],
    }
  }
  return {
    level: 'success',
    title: '不同市场状态下表现相对均衡，策略具备一定环境适应性。',
    tips: ['继续关注状态切换时的回撤变化，避免在单一状态下过度优化。'],
  }
}

function buildMonteCarloAdvice(monteCarlo: BacktestMonteCarloSummary | null): AnalysisAdvice | null {
  if (!monteCarlo || Number(monteCarlo.simulations || 0) <= 0) {
    return {
      level: 'info',
      title: '交易样本不足，暂未生成有效的蒙特卡洛压力测试。',
      tips: ['建议至少积累更多成交样本后再看尾部风险。'],
    }
  }
  const ruin = Number(monteCarlo.ruin_probability || 0)
  const p50 = Number(monteCarlo.total_return_p50 || 0)
  const p5 = Number(monteCarlo.total_return_p5 || 0)
  if (ruin >= 0.4 || p50 < -0.1) {
    return {
      level: 'error',
      title: '压力测试结果偏弱：中位收益或极端亏损概率都处于高风险区间。',
      tips: [
        '优先降低单笔仓位和最大并发持仓，先把尾部亏损压下来。',
        '收紧止损并降低持仓天数，避免单笔亏损拖垮整体权益。',
      ],
    }
  }
  if (ruin >= 0.2 || p5 < -0.25) {
    return {
      level: 'warning',
      title: '存在明显尾部风险：常规表现可接受，但坏场景下回撤仍偏大。',
      tips: [
        '建议先做“保守参数”版本（更低仓位、更紧止损）作为实盘基线。',
        '对高波动标的减少配置，降低组合回撤耦合。',
      ],
    }
  }
  return {
    level: 'success',
    title: '压力测试可接受：尾部风险相对受控，参数具备一定抗扰动能力。',
    tips: ['继续用滚动窗口复测，确认不同年份下压力结果一致。'],
  }
}

function buildWalkForwardAdvice(walkForward: BacktestWalkForwardReport | null): AnalysisAdvice | null {
  if (!walkForward || Number(walkForward.fold_count || 0) <= 0) {
    return {
      level: 'info',
      title: 'Walk-forward 未执行或无有效折叠，暂无法判断样本外泛化能力。',
      tips: ['扩大回测区间并确保交易样本充足后再评估 OOS 通过率。'],
    }
  }
  const passRate = Number(walkForward.oos_pass_rate || 0)
  const avgReturn = Number(walkForward.avg_test_return || 0)
  if (passRate >= 0.67 && avgReturn > 0) {
    return {
      level: 'success',
      title: '样本外验证较好：多数折叠通过，策略具备一定泛化能力。',
      tips: ['保持当前参数区间，优先做执行层优化（滑点、成交约束、风控细节）。'],
    }
  }
  if (passRate > 0) {
    return {
      level: 'warning',
      title: '样本外通过率一般：参数有效性不够稳定，存在阶段性失效风险。',
      tips: [
        '缩小参数搜索空间，优先选择在多折叠中表现更均衡的参数。',
        '将训练目标从“高收益”转为“低回撤+可接受收益”。',
      ],
    }
  }
  return {
    level: 'error',
    title: '样本外通过率为 0：当前参数在新样本下不可用，过拟合风险较高。',
    tips: [
      '重新设计入场/出场约束，先追求可复制性再追求收益峰值。',
      '增加稳健性约束（最低胜率、最大回撤上限）后再进行参数搜索。',
    ],
  }
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

function plateauTaskStatusLabel(status: BacktestPlateauTaskStatusResponse['status']) {
  if (status === 'pending') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'paused') return '已暂停'
  if (status === 'succeeded') return '已完成'
  if (status === 'cancelled') return '已停止'
  return '失败'
}

function plateauTaskStatusColor(status: BacktestPlateauTaskStatusResponse['status']) {
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
  {
    title: '入场事件',
    dataIndex: 'entry_signal',
    width: 130,
    render: (value: string) => formatEventSequence(value) || '--',
  },
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
  const initialPlateauDraft = useMemo(() => loadBacktestPlateauDraft(), [])

  const [mode, setMode] = useState<SignalScanMode>(initialDraft.mode)
  const [trendStep, setTrendStep] = useState<TrendPoolStep>(initialDraft.trend_step)
  const [poolRollMode, setPoolRollMode] = useState<BacktestPoolRollMode>(initialDraft.pool_roll_mode)
  const [runId, setRunId] = useState(initialDraft.run_id)
  const [boardFilters, setBoardFilters] = useState<BoardFilter[]>(initialDraft.board_filters)
  const [strategyId, setStrategyId] = useState<StrategyId>(() => getSharedLastStrategyId(initialDraft.strategy_id))
  const [strategyParams, setStrategyParams] = useState<Record<string, unknown>>(() => {
    const seedStrategyId = getSharedLastStrategyId(initialDraft.strategy_id)
    const draftParams = normalizeStrategyParams(initialDraft.strategy_params)
    if (Object.keys(draftParams).length > 0) return draftParams
    return getSharedStrategyParams(seedStrategyId)
  })
  const [strategyPresetName, setStrategyPresetName] = useState('')
  const [strategyPresetId, setStrategyPresetId] = useState<string | null>(null)
  const [strategyPresetRefreshTick, setStrategyPresetRefreshTick] = useState(0)
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
  const [entryDelayDays, setEntryDelayDays] = useState(initialDraft.entry_delay_days)
  const [delayInvalidationEnabled, setDelayInvalidationEnabled] = useState(initialDraft.delay_invalidation_enabled)
  const [maxSymbols, setMaxSymbols] = useState(initialDraft.max_symbols)
  const [enableAdvancedAnalysis, setEnableAdvancedAnalysis] = useState(initialDraft.enable_advanced_analysis)
  const [plateauSamplingMode, setPlateauSamplingMode] = useState<'grid' | 'lhs'>(initialPlateauDraft.sampling_mode)
  const [plateauSamplePoints, setPlateauSamplePoints] = useState(initialPlateauDraft.sample_points)
  const [plateauRandomSeed, setPlateauRandomSeed] = useState<number | null>(initialPlateauDraft.random_seed)
  const [plateauWindowListRaw, setPlateauWindowListRaw] = useState(initialPlateauDraft.window_days_list_raw)
  const [plateauMinScoreListRaw, setPlateauMinScoreListRaw] = useState(initialPlateauDraft.min_score_list_raw)
  const [plateauStopLossPctListRaw, setPlateauStopLossPctListRaw] = useState(initialPlateauDraft.stop_loss_pct_list_raw)
  const [plateauTakeProfitPctListRaw, setPlateauTakeProfitPctListRaw] = useState(initialPlateauDraft.take_profit_pct_list_raw)
  const [plateauMaxPositionsListRaw, setPlateauMaxPositionsListRaw] = useState(initialPlateauDraft.max_positions_list_raw)
  const [plateauPositionPctListRaw, setPlateauPositionPctListRaw] = useState(initialPlateauDraft.position_pct_list_raw)
  const [plateauMaxSymbolsListRaw, setPlateauMaxSymbolsListRaw] = useState(initialPlateauDraft.max_symbols_list_raw)
  const [plateauTopKListRaw, setPlateauTopKListRaw] = useState(initialPlateauDraft.topk_list_raw)
  const [plateauError, setPlateauError] = useState<string | null>(null)
  const [plateauApplyRank, setPlateauApplyRank] = useState(1)
  const [plateauHeatmapXAxis, setPlateauHeatmapXAxis] = useState<PlateauAxisKey>(initialPlateauDraft.heatmap_x_axis)
  const [plateauHeatmapYAxis, setPlateauHeatmapYAxis] = useState<PlateauAxisKey>(initialPlateauDraft.heatmap_y_axis)
  const [plateauHeatmapMetric, setPlateauHeatmapMetric] = useState<PlateauMetricKey>(initialPlateauDraft.heatmap_metric)
  const [plateauHeatmapShowBestPath, setPlateauHeatmapShowBestPath] = useState(initialPlateauDraft.heatmap_show_best_path)
  const [plateauHeatmapShowCellLabel, setPlateauHeatmapShowCellLabel] = useState(initialPlateauDraft.heatmap_show_cell_label)
  const [plateauHeatmapSelectedCoord, setPlateauHeatmapSelectedCoord] = useState<[string, string] | null>(null)
  const [plateauBrushSelectedKeys, setPlateauBrushSelectedKeys] = useState<string[]>([])
  const [plateauCandidatePoints, setPlateauCandidatePoints] = useState<BacktestPlateauPoint[]>([])
  const [plateauCandidatePickRank, setPlateauCandidatePickRank] = useState(1)
  const [plateauSavedPresets, setPlateauSavedPresets] = useState<BacktestPlateauPreset[]>(() => loadBacktestPlateauPresets())
  const [plateauSavedPresetId, setPlateauSavedPresetId] = useState<string | null>(null)
  const [tradePage, setTradePage] = useState(1)
  const [tradePageSize, setTradePageSize] = useState(initialDraft.trades_page_size)
  const [runError, setRunError] = useState<string | null>(null)
  const [reportLibrary, setReportLibrary] = useState<BacktestReportSummary[]>([])
  const [reportLibraryLoading, setReportLibraryLoading] = useState(false)
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null)
  const [abAutoGenerateDefaults, setAbAutoGenerateDefaults] = useState(true)
  const [abMaxVariants, setAbMaxVariants] = useState(16)
  const [abCustomVariantsText, setAbCustomVariantsText] = useState('')
  const [abResult, setAbResult] = useState<BacktestABExperimentResponse | null>(null)
  const [abError, setAbError] = useState<string | null>(null)
  const importReportFileRef = useRef<HTMLInputElement | null>(null)
  const tasksById = useBacktestTaskStore((state) => state.tasksById)
  const payloadById = useBacktestTaskStore((state) => state.payloadById)
  const activeTaskIds = useBacktestTaskStore((state) => state.activeTaskIds)
  const selectedTaskId = useBacktestTaskStore((state) => state.selectedTaskId)
  const enqueueTask = useBacktestTaskStore((state) => state.enqueueTask)
  const upsertTaskPayload = useBacktestTaskStore((state) => state.upsertTaskPayload)
  const upsertTaskStatus = useBacktestTaskStore((state) => state.upsertTaskStatus)
  const setSelectedTask = useBacktestTaskStore((state) => state.setSelectedTask)
  const plateauTasksById = useBacktestPlateauTaskStore((state) => state.tasksById)
  const plateauActiveTaskIds = useBacktestPlateauTaskStore((state) => state.activeTaskIds)
  const plateauSelectedTaskId = useBacktestPlateauTaskStore((state) => state.selectedTaskId)
  const enqueuePlateauTask = useBacktestPlateauTaskStore((state) => state.enqueueTask)
  const upsertPlateauTaskStatus = useBacktestPlateauTaskStore((state) => state.upsertTaskStatus)
  const setSelectedPlateauTask = useBacktestPlateauTaskStore((state) => state.setSelectedTask)

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
  const riskMetrics = result?.risk_metrics ?? null
  const stabilityDiagnostics = result?.stability_diagnostics ?? null
  const regimeBreakdown = result?.regime_breakdown ?? []
  const monteCarlo = result?.monte_carlo ?? null
  const walkForward = result?.walk_forward ?? null
  const stabilityAdvice = useMemo(() => buildStabilityAdvice(stabilityDiagnostics), [stabilityDiagnostics])
  const regimeAdvice = useMemo(() => buildRegimeAdvice(regimeBreakdown), [regimeBreakdown])
  const monteCarloAdvice = useMemo(() => buildMonteCarloAdvice(monteCarlo), [monteCarlo])
  const walkForwardAdvice = useMemo(() => buildWalkForwardAdvice(walkForward), [walkForward])
  const selectedTaskPayload = selectedTaskId ? payloadById[selectedTaskId] ?? null : null
  const runningTaskCount = activeTaskIds.length
  const plateauTaskOptions = useMemo(
    () =>
      Object.values(plateauTasksById)
        .sort((left, right) => {
          const leftTs = Date.parse(left.progress.updated_at || left.progress.started_at || '')
          const rightTs = Date.parse(right.progress.updated_at || right.progress.started_at || '')
          return rightTs - leftTs
        })
        .map((task) => ({
          value: task.task_id,
          label: `${plateauTaskStatusLabel(task.status)} | ${task.task_id.slice(0, 12)} | ${task.progress.updated_at}`,
        })),
    [plateauTasksById],
  )
  const plateauTaskStatus = plateauSelectedTaskId ? plateauTasksById[plateauSelectedTaskId] ?? null : null
  const plateauTaskProgress = plateauTaskStatus?.progress
  const plateauResult = plateauTaskStatus?.result ?? null
  const plateauTaskRunningCount = plateauActiveTaskIds.length
  const strategyCatalogQuery = useQuery({
    queryKey: ['strategy-catalog'],
    queryFn: getStrategies,
    staleTime: 5 * 60_000,
  })
  const strategyItems = strategyCatalogQuery.data?.items ?? []
  const selectedStrategy = useMemo(
    () => strategyItems.find((item) => item.strategy_id === strategyId) ?? null,
    [strategyId, strategyItems],
  )
  const strategyParamsSchema = useMemo(
    () => parseStrategyParamSchema(selectedStrategy?.strategy_params_schema ?? {}),
    [selectedStrategy?.strategy_params_schema],
  )
  const strategyParamsDefaults = useMemo(
    () => normalizeStrategyParams(selectedStrategy?.strategy_params_defaults),
    [selectedStrategy?.strategy_params_defaults],
  )
  const strategyParamsPayload = useMemo(
    () => buildStrategyParamsPayload({
      schema: strategyParamsSchema,
      params: strategyParams,
      defaults: strategyParamsDefaults,
      includeDefaults: true,
    }),
    [strategyParams, strategyParamsDefaults, strategyParamsSchema],
  )

  useEffect(() => {
    if (strategyItems.length <= 0) return
    const allIds = new Set(strategyItems.map((item) => item.strategy_id))
    if (allIds.has(strategyId)) return
    const defaultId = resolveDefaultStrategyId(strategyItems, 'wyckoff_trend_v1')
    setStrategyId(defaultId)
  }, [strategyId, strategyItems])

  useEffect(() => {
    if (!selectedStrategy) return
    setStrategyParams((previous) => {
      const normalizedPrevious = normalizeStrategyParams(previous)
      const merged = {
        ...strategyParamsDefaults,
        ...normalizedPrevious,
      }
      const next = buildStrategyParamsPayload({
        schema: strategyParamsSchema,
        params: merged,
        defaults: strategyParamsDefaults,
        includeDefaults: true,
      })
      return JSON.stringify(next) === JSON.stringify(normalizedPrevious) ? previous : next
    })
  }, [selectedStrategy?.strategy_id, strategyParamsDefaults, strategyParamsSchema])

  useEffect(() => {
    setSharedStrategyParams(strategyId, strategyParamsPayload)
  }, [strategyId, strategyParamsPayload])

  const strategyParamEntries = useMemo<StrategyParamSpec[]>(
    () => Object.values(strategyParamsSchema),
    [strategyParamsSchema],
  )
  const strategyPresets = useMemo<StrategyParamPreset[]>(
    () => listSharedStrategyPresets(strategyId),
    [strategyId, strategyPresetRefreshTick],
  )
  const selectedStrategyPreset = useMemo(
    () => strategyPresets.find((item) => item.id === strategyPresetId) ?? null,
    [strategyPresetId, strategyPresets],
  )

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
      strategy_id: strategyId,
      strategy_params: strategyParamsPayload,
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
      entry_delay_days: entryDelayDays,
      delay_invalidation_enabled: delayInvalidationEnabled,
      max_symbols: maxSymbols,
      enable_advanced_analysis: enableAdvancedAnalysis,
      trades_page_size: tradePageSize,
    }
    persistBacktestDraft(draft)
  }, [
    mode,
    trendStep,
    poolRollMode,
    runId,
    boardFilters,
    strategyId,
    strategyParamsPayload,
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
    entryDelayDays,
    delayInvalidationEnabled,
    maxSymbols,
    enableAdvancedAnalysis,
    tradePageSize,
  ])

  const startTaskMutation = useMutation({
    mutationFn: startBacktestTask,
    onSuccess: (payload, variables) => {
      enqueueTask(payload.task_id, variables.pool_roll_mode, variables)
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

  const startPlateauTaskMutation = useMutation({
    mutationFn: startBacktestPlateauTask,
    onSuccess: (payload, variables) => {
      enqueuePlateauTask(payload.task_id, variables.sampling_mode ?? 'lhs')
      setSelectedPlateauTask(payload.task_id)
      setPlateauError(null)
      message.info('收益平原任务已提交，正在后台评估参数组合...')
    },
    onError: (error) => {
      const text = formatApiError(error)
      setPlateauError(text)
      message.error(text)
    },
  })

  const runABExperimentMutation = useMutation({
    mutationFn: runBacktestABExperiment,
    onSuccess: (payload) => {
      setAbResult(payload)
      setAbError(null)
      message.success(`A/B 实验完成：共 ${payload.variants.length} 个变体。`)
    },
    onError: (error) => {
      const text = formatApiError(error)
      setAbError(text)
      message.error(text)
    },
  })

  const controlPlateauTaskMutation = useMutation({
    mutationFn: async (payload: { action: 'pause' | 'resume' | 'cancel'; taskId: string }) => {
      if (payload.action === 'pause') return pauseBacktestPlateauTask(payload.taskId)
      if (payload.action === 'resume') return resumeBacktestPlateauTask(payload.taskId)
      return cancelBacktestPlateauTask(payload.taskId)
    },
    onSuccess: (status, variables) => {
      upsertPlateauTaskStatus(status)
      if (variables.action === 'pause') {
        message.info(`收益平原任务已暂停：${status.task_id}`)
      } else if (variables.action === 'resume') {
        message.success(`收益平原任务已继续：${status.task_id}`)
      } else {
        message.warning(`收益平原任务已停止：${status.task_id}`)
      }
    },
    onError: (error) => {
      message.error(formatApiError(error))
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

  async function refreshReportLibrary(preferredReportId?: string | null) {
    setReportLibraryLoading(true)
    try {
      const response = await listBacktestReports()
      const rows = response.items
      setReportLibrary(rows)
      setSelectedReportId((current) => {
        const preferred = preferredReportId === undefined ? current : preferredReportId
        if (preferred && rows.some((item) => item.report_id === preferred)) return preferred
        return rows[0]?.report_id ?? null
      })
    } catch (error) {
      message.error(formatApiError(error))
    } finally {
      setReportLibraryLoading(false)
    }
  }

  const exportReportMutation = useMutation({
    mutationFn: buildBacktestReportPackage,
    onSuccess: (payload) => {
      const bytes = base64ToUint8Array(payload.file_base64)
      const safeBytes = new Uint8Array(bytes.byteLength)
      safeBytes.set(bytes)
      const blob = new Blob([safeBytes], { type: 'application/octet-stream' })
      downloadBlob(payload.file_name, blob)
      message.success(`回测报告已导出：${payload.file_name}`)
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const importReportMutation = useMutation({
    mutationFn: importBacktestReportPackage,
    onSuccess: (payload) => {
      message.success(`报告导入成功：${payload.summary.report_id}`)
      void refreshReportLibrary(payload.summary.report_id)
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const loadReportMutation = useMutation({
    mutationFn: getBacktestReport,
    onSuccess: (payload) => {
      const taskId = `imp_${payload.summary.report_id}`
      const status: BacktestTaskStatusResponse = {
        task_id: taskId,
        status: 'succeeded',
        progress: {
          mode: payload.run_request.pool_roll_mode,
          current_date: payload.run_result.range.date_to,
          processed_dates: 1,
          total_dates: 1,
          percent: 100,
          message: `已加载导入报告（${payload.summary.report_id}）`,
          warning: null,
          stage_timings: [],
          started_at: payload.summary.first_imported_at,
          updated_at: payload.summary.last_imported_at,
        },
        result: payload.run_result,
        error: null,
        error_code: null,
      }
      upsertTaskStatus(status)
      upsertTaskPayload(taskId, payload.run_request)
      setSelectedTask(taskId)
      if (payload.plateau_result) {
        const plateauTaskId = `imp_plateau_${payload.summary.report_id}`
        const normalizedPlateauResult: BacktestPlateauResponse = {
          ...payload.plateau_result,
          correlations: resolvePlateauCorrelations(payload.plateau_result),
        }
        const plateauStatus: BacktestPlateauTaskStatusResponse = {
          task_id: plateauTaskId,
          status: 'succeeded',
          progress: {
            sampling_mode: 'lhs',
            processed_points: Number(normalizedPlateauResult.evaluated_combinations || 0),
            total_points: Number(normalizedPlateauResult.total_combinations || 0),
            percent: 100,
            message: `已加载导入平原结果（${payload.summary.report_id}）`,
            started_at: payload.summary.first_imported_at,
            updated_at: payload.summary.last_imported_at,
          },
          result: normalizedPlateauResult,
          error: null,
          error_code: null,
        }
        upsertPlateauTaskStatus(plateauStatus)
        setSelectedPlateauTask(plateauTaskId)
      }
      message.success(`已加载导入报告：${payload.summary.report_id}`)
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteBacktestReport,
    onSuccess: (payload) => {
      message.success(`已删除报告：${payload.report_id}`)
      void refreshReportLibrary()
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  function buildReportExportPayload() {
    if (!result) {
      message.warning('暂无可导出的回测结果')
      return null
    }
    if (!selectedTaskPayload) {
      message.warning('当前任务缺少参数快照（旧任务），请重新运行一次后再导出')
      return null
    }
    try {
      const exportPlateauResult: BacktestPlateauResponse | null = plateauResult
        ? {
            ...plateauResult,
            correlations: resolvePlateauCorrelations(plateauResult),
          }
        : null
      const workbookBuffer = buildBacktestReportWorkbookBuffer(selectedTaskPayload, result, exportPlateauResult)
      const reportHtml = buildBacktestReportHtml(selectedTaskPayload, result, exportPlateauResult)
      const dateFrom = String(result.range.date_from || '').replaceAll('-', '')
      const dateTo = String(result.range.date_to || '').replaceAll('-', '')
      const fileBaseName = [
        'backtest_report',
        String(selectedTaskPayload.mode || 'backtest'),
        dateFrom || 'from',
        dateTo || 'to',
        dayjs().format('YYYYMMDD_HHmmss'),
      ]
        .join('_')
        .replace(/[^0-9A-Za-z_.-]/g, '_')
      return {
        runRequest: selectedTaskPayload,
        runResult: result,
        exportPlateauResult,
        workbookBuffer,
        reportHtml,
        fileBaseName,
      }
    } catch (error) {
      message.error(formatApiError(error))
      return null
    }
  }

  function handleExportFtbt() {
    const payload = buildReportExportPayload()
    if (!payload) return
    const reportXlsxBase64 = bufferToBase64(payload.workbookBuffer)
    exportReportMutation.mutate({
      run_request: payload.runRequest,
      run_result: payload.runResult,
      report_html: payload.reportHtml,
      report_xlsx_base64: reportXlsxBase64,
      plateau_result: payload.exportPlateauResult,
      app_name: 'Final Trade',
      app_version: String(import.meta.env.VITE_APP_VERSION || 'frontend'),
    })
  }

  function handleExportXlsxReport() {
    const payload = buildReportExportPayload()
    if (!payload) return
    const blob = new Blob([payload.workbookBuffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const fileName = `${payload.fileBaseName}.xlsx`
    downloadBlob(fileName, blob)
    message.success(`已导出 Excel 报告：${fileName}`)
  }

  function handleExportHtmlReport() {
    const payload = buildReportExportPayload()
    if (!payload) return
    const blob = new Blob([payload.reportHtml], { type: 'text/html;charset=utf-8' })
    const fileName = `${payload.fileBaseName}.html`
    downloadBlob(fileName, blob)
    message.success(`已导出 HTML 报告：${fileName}`)
  }

  function handleImportFtbt(file: File | null | undefined) {
    if (!file) return
    if (!String(file.name || '').toLowerCase().endsWith('.ftbt')) {
      message.warning('仅支持导入 .ftbt 文件')
      return
    }
    importReportMutation.mutate(file)
  }

  function handleLoadSelectedReport() {
    if (!selectedReportId) {
      message.warning('请先选择报告')
      return
    }
    loadReportMutation.mutate(selectedReportId)
  }

  function handleDeleteSelectedReport() {
    if (!selectedReportId) {
      message.warning('请先选择报告')
      return
    }
    deleteReportMutation.mutate(selectedReportId)
  }

  useEffect(() => {
    void refreshReportLibrary()
  }, [])

  useEffect(() => {
    setTradePage(1)
  }, [result?.trades])

  useEffect(() => {
    const draft: BacktestPlateauFormDraft = {
      sampling_mode: plateauSamplingMode,
      sample_points: plateauSamplePoints,
      random_seed: plateauRandomSeed,
      window_days_list_raw: plateauWindowListRaw,
      min_score_list_raw: plateauMinScoreListRaw,
      stop_loss_pct_list_raw: plateauStopLossPctListRaw,
      take_profit_pct_list_raw: plateauTakeProfitPctListRaw,
      max_positions_list_raw: plateauMaxPositionsListRaw,
      position_pct_list_raw: plateauPositionPctListRaw,
      max_symbols_list_raw: plateauMaxSymbolsListRaw,
      topk_list_raw: plateauTopKListRaw,
      heatmap_x_axis: plateauHeatmapXAxis,
      heatmap_y_axis: plateauHeatmapYAxis,
      heatmap_metric: plateauHeatmapMetric,
      heatmap_show_best_path: plateauHeatmapShowBestPath,
      heatmap_show_cell_label: plateauHeatmapShowCellLabel,
    }
    persistBacktestPlateauDraft(draft)
  }, [
    plateauSamplingMode,
    plateauSamplePoints,
    plateauRandomSeed,
    plateauWindowListRaw,
    plateauMinScoreListRaw,
    plateauStopLossPctListRaw,
    plateauTakeProfitPctListRaw,
    plateauMaxPositionsListRaw,
    plateauPositionPctListRaw,
    plateauMaxSymbolsListRaw,
    plateauTopKListRaw,
    plateauHeatmapXAxis,
    plateauHeatmapYAxis,
    plateauHeatmapMetric,
    plateauHeatmapShowBestPath,
    plateauHeatmapShowCellLabel,
  ])

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

  useEffect(() => {
    if (plateauSelectedTaskId) return
    if (plateauTaskOptions.length <= 0) return
    const firstTaskId = String(plateauTaskOptions[0]?.value || '').trim()
    if (!firstTaskId) return
    setSelectedPlateauTask(firstTaskId)
  }, [plateauSelectedTaskId, plateauTaskOptions, setSelectedPlateauTask])

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
      strategy_id: strategyId,
      strategy_params: strategyParamsPayload,
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
      entry_delay_days: entryDelayDays,
      delay_invalidation_enabled: delayInvalidationEnabled,
      max_symbols: maxSymbols,
      enable_advanced_analysis: enableAdvancedAnalysis,
    }
  }

  function updateStrategyParam(key: string, value: unknown) {
    const normalizedKey = String(key || '').trim()
    if (!normalizedKey) return
    setStrategyParams((previous) => {
      const next = { ...normalizeStrategyParams(previous) }
      if (value === null || value === undefined || value === '') {
        delete next[normalizedKey]
      } else {
        next[normalizedKey] = value
      }
      return next
    })
  }

  function handleSaveStrategyPreset() {
    const preset = saveSharedStrategyPreset({
      strategyId,
      name: strategyPresetName || `${strategyId}-${dayjs().format('MMDD-HHmm')}`,
      params: strategyParamsPayload,
    })
    setStrategyPresetId(preset.id)
    setStrategyPresetName(preset.name)
    setStrategyPresetRefreshTick((value) => value + 1)
    message.success(`已保存策略预设：${preset.name}`)
  }

  function handleApplyStrategyPreset() {
    if (!selectedStrategyPreset) {
      message.info('请先选择策略预设。')
      return
    }
    setStrategyParams(normalizeStrategyParams(selectedStrategyPreset.strategy_params))
    setRunError(null)
    message.success(`已应用策略预设：${selectedStrategyPreset.name}`)
  }

  function handleDeleteStrategyPreset() {
    if (!selectedStrategyPreset) {
      message.info('请先选择策略预设。')
      return
    }
    deleteSharedStrategyPreset(strategyId, selectedStrategyPreset.id)
    setStrategyPresetId(null)
    setStrategyPresetRefreshTick((value) => value + 1)
    message.success(`已删除策略预设：${selectedStrategyPreset.name}`)
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

  function parseABCustomVariants(text: string): BacktestABVariantConfig[] | null {
    const raw = String(text || '').trim()
    if (!raw) return []
    try {
      const parsed = JSON.parse(raw) as unknown
      if (!Array.isArray(parsed)) {
        message.warning('自定义 A/B 变体格式错误：请提供 JSON 数组。')
        return null
      }
      return parsed as BacktestABVariantConfig[]
    } catch {
      message.warning('自定义 A/B 变体 JSON 解析失败，请检查格式。')
      return null
    }
  }

  function handleRunABExperiment() {
    if (runABExperimentMutation.isPending) return
    if (entryEvents.length === 0 || exitEvents.length === 0) {
      message.warning('请至少选择一个入场事件和离场事件')
      return
    }
    const cached = readScreenerRunMetaFromStorage()
    const effectiveBoardFilters = cached?.boardFilters?.length ? cached.boardFilters : boardFilters
    const shouldApplyBoardFilters = mode === 'trend_pool'
    if (shouldApplyBoardFilters && effectiveBoardFilters.length === 0) {
      message.warning('请至少选择一个板块后再运行 A/B')
      return
    }
    if (cached?.boardFilters?.length) {
      setBoardFilters(cached.boardFilters)
    }

    const customVariants = parseABCustomVariants(abCustomVariantsText)
    if (customVariants === null) return
    const payload = {
      base_payload: buildBacktestPayload(shouldApplyBoardFilters ? effectiveBoardFilters : undefined),
      variants: customVariants,
      auto_generate_default_matrix: abAutoGenerateDefaults,
      max_variants: Math.max(1, Math.min(64, Math.round(Number(abMaxVariants) || 16))),
    }
    setAbError(null)
    runABExperimentMutation.mutate(payload)
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
    if (startPlateauTaskMutation.isPending) return
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
    startPlateauTaskMutation.mutate(payload)
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
  const plateauLoading = startPlateauTaskMutation.isPending
  const plateauTaskRunning =
    plateauTaskStatus?.status === 'running'
    || plateauTaskStatus?.status === 'pending'
    || plateauTaskStatus?.status === 'paused'
  const effectivePlateauError =
    plateauError
    || (plateauTaskStatus?.status === 'failed'
      ? (plateauTaskStatus.error?.trim() || '收益平原任务失败')
      : null)
  const plateauBestPoint = plateauResult?.best_point ?? null
  const plateauValidPoints = useMemo(
    () => (plateauResult?.points ?? []).filter((row) => !row.error),
    [plateauResult?.points],
  )
  const plateauCorrelationRows = useMemo(
    () => resolvePlateauCorrelations(plateauResult),
    [plateauResult],
  )
  const plateauCorrelationColumns = useMemo<ColumnsType<BacktestPlateauCorrelationRow>>(
    () => [
      {
        title: '参数',
        dataIndex: 'parameter_label',
        width: 180,
      },
      {
        title: '与评分相关',
        width: 160,
        render: (_value, row) => {
          const direction = classifyCorrelationDirection(row.score_corr)
          return (
            <Space size={6}>
              <span>{formatSigned(row.score_corr)}</span>
              <Tag color={correlationDirectionTagColor(direction)}>{direction}</Tag>
            </Space>
          )
        },
      },
      {
        title: '与收益相关',
        width: 160,
        render: (_value, row) => {
          const direction = classifyCorrelationDirection(row.total_return_corr)
          return (
            <Space size={6}>
              <span>{formatSigned(row.total_return_corr)}</span>
              <Tag color={correlationDirectionTagColor(direction)}>{direction}</Tag>
            </Space>
          )
        },
      },
      {
        title: '与胜率相关',
        width: 160,
        render: (_value, row) => {
          const direction = classifyCorrelationDirection(row.win_rate_corr)
          return (
            <Space size={6}>
              <span>{formatSigned(row.win_rate_corr)}</span>
              <Tag color={correlationDirectionTagColor(direction)}>{direction}</Tag>
            </Space>
          )
        },
      },
    ],
    [],
  )
  const regimeColumns = useMemo<ColumnsType<BacktestRegimeBucket>>(
    () => [
      {
        title: '状态',
        dataIndex: 'label',
        width: 120,
      },
      {
        title: '交易数',
        dataIndex: 'trade_count',
        width: 90,
      },
      {
        title: '胜率',
        dataIndex: 'win_rate',
        width: 100,
        render: (value: number) => formatPct(Number(value)),
      },
      {
        title: '总收益',
        dataIndex: 'total_return',
        width: 110,
        render: (value: number) => formatPct(Number(value)),
      },
      {
        title: '平均单笔',
        dataIndex: 'avg_pnl_ratio',
        width: 110,
        render: (value: number) => formatPct(Number(value)),
      },
      {
        title: '最大回撤',
        dataIndex: 'max_drawdown',
        width: 110,
        render: (value: number) => formatPct(Number(value)),
      },
    ],
    [],
  )
  const walkForwardColumns = useMemo<ColumnsType<BacktestWalkForwardReport['folds'][number]>>(
    () => [
      {
        title: 'Fold',
        dataIndex: 'fold_index',
        width: 70,
      },
      {
        title: '训练区间',
        width: 220,
        render: (_value, row) => `${row.train_date_from} ~ ${row.train_date_to}`,
      },
      {
        title: '测试区间',
        width: 220,
        render: (_value, row) => `${row.test_date_from} ~ ${row.test_date_to}`,
      },
      {
        title: '训练评分',
        dataIndex: 'train_score',
        width: 100,
        render: (value: number) => Number(value).toFixed(3),
      },
      {
        title: '测试评分',
        dataIndex: 'test_score',
        width: 100,
        render: (value: number) => Number(value).toFixed(3),
      },
      {
        title: '测试收益',
        width: 110,
        render: (_value, row) => formatPct(Number(row.test_stats.total_return)),
      },
      {
        title: '测试胜率',
        width: 110,
        render: (_value, row) => formatPct(Number(row.test_stats.win_rate)),
      },
      {
        title: '入选参数',
        width: 320,
        render: (_value, row) => {
          const p = row.selected_params
          return `window=${p.window_days}, min=${Number(p.min_score).toFixed(2)}, sl=${(Number(p.stop_loss) * 100).toFixed(2)}%, tp=${(Number(p.take_profit) * 100).toFixed(2)}%`
        },
      },
    ],
    [],
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
      width: 150,
      render: (_value, row) => (
        <Space size={6}>
          <Button
            size="small"
            disabled={Boolean(row.error)}
            onClick={() => applyPlateauPointToForm(row, `第${row.__rank}名`)}
          >
            回填
          </Button>
          <Button
            size="small"
            disabled={Boolean(row.error)}
            onClick={() => savePlateauPreset(row, `第${row.__rank}名`)}
          >
            保存
          </Button>
        </Space>
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
    const rowsForShare = normalized.filter((row) => !(row.stageKey === 'run_total' || row.stageKey.endsWith('_total')))
    const totalMs = (rowsForShare.length > 0 ? rowsForShare : normalized).reduce((acc, row) => acc + row.elapsedMs, 0)
    return {
      totalMs,
      rows: normalized.map((row) => ({
        ...row,
        elapsedSecText: `${(row.elapsedMs / 1000).toFixed(2)}s`,
        shareText:
          row.stageKey === 'run_total' || row.stageKey.endsWith('_total')
            ? '--'
            : (totalMs > 0 ? `${((row.elapsedMs / totalMs) * 100).toFixed(1)}%` : '0.0%'),
      })),
    }
  }, [taskProgress?.stage_timings])
  const abVariantRows = abResult?.variants ?? []
  const abComparisonRows = abResult?.comparisons ?? []
  const abVariantColumns = useMemo<ColumnsType<BacktestABVariantResult>>(
    () => [
      { title: '变体ID', dataIndex: 'variant_id', width: 92 },
      { title: '标签', dataIndex: 'label', width: 220 },
      {
        title: '状态',
        dataIndex: 'status',
        width: 96,
        render: (value: BacktestABVariantResult['status']) =>
          value === 'succeeded' ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag>,
      },
      {
        title: '总收益',
        width: 110,
        render: (_value, row) => (row.stats ? formatPct(row.stats.total_return) : '--'),
      },
      {
        title: '胜率',
        width: 100,
        render: (_value, row) => (row.stats ? formatPct(row.stats.win_rate) : '--'),
      },
      {
        title: '最大回撤',
        width: 110,
        render: (_value, row) => (row.stats ? formatPct(row.stats.max_drawdown) : '--'),
      },
      { title: '交易数', dataIndex: 'trade_count', width: 90 },
      {
        title: 'UTAD占比',
        width: 108,
        render: (_value, row) => formatPct(row.utad_exit_ratio),
      },
      { title: '最大连亏', dataIndex: 'max_consecutive_losses', width: 100 },
      {
        title: '按入场信号分组',
        width: 260,
        render: (_value, row) => {
          const buckets = Array.isArray(row.signal_breakdown) ? row.signal_breakdown : []
          if (buckets.length <= 0) return '--'
          return buckets
            .map((item) => `${item.signal}:${item.trade_count}笔/${formatPct(item.win_rate)}`)
            .join(' | ')
        },
      },
      {
        title: '错误',
        dataIndex: 'error',
        width: 260,
        ellipsis: true,
      },
    ],
    [],
  )
  const abComparisonColumns = useMemo<ColumnsType<BacktestABComparisonRow>>(
    () => [
      { title: '变体ID', dataIndex: 'variant_id', width: 92 },
      { title: '标签', dataIndex: 'label', width: 220 },
      {
        title: '收益Δ',
        width: 100,
        render: (_value, row) => formatPct(row.total_return_delta),
      },
      {
        title: '胜率Δ',
        width: 100,
        render: (_value, row) => formatPct(row.win_rate_delta),
      },
      {
        title: '回撤Δ',
        width: 100,
        render: (_value, row) => formatPct(row.max_drawdown_delta),
      },
      {
        title: 'UTAD占比Δ',
        width: 120,
        render: (_value, row) => formatPct(row.utad_exit_ratio_delta),
      },
      {
        title: '最大连亏Δ',
        dataIndex: 'max_consecutive_losses_delta',
        width: 110,
      },
    ],
    [],
  )

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
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>策略</span>
              <Select
                loading={strategyCatalogQuery.isLoading}
                value={strategyId}
                onChange={(value) => {
                  const next = String(value) as StrategyId
                  setStrategyId(next)
                  setStrategyParams(getSharedStrategyParams(next))
                  setStrategyPresetId(null)
                }}
                options={(strategyItems.length > 0
                  ? strategyItems
                  : [{ strategy_id: 'wyckoff_trend_v1', name: 'Wyckoff Trend V1', version: '1.0.0', enabled: true }])
                  .map((item) => ({
                    value: item.strategy_id,
                    label: `${item.name} (${item.version})${item.enabled === false ? ' - disabled' : ''}`,
                    disabled: item.enabled === false,
                  }))}
              />
            </Space>
          </Col>
          <Col xs={24} md={18}>
            <Alert
              type="info"
              showIcon
              title={selectedStrategy ? `策略：${selectedStrategy.name}` : '策略信息'}
              description={
                selectedStrategy
                  ? `id=${selectedStrategy.strategy_id}, version=${selectedStrategy.version}`
                  : '未加载到策略目录，先按默认策略继续。'
              }
            />
          </Col>

          {strategyParamEntries.length > 0 ? (
            <Col xs={24}>
              <Card size="small" title="策略参数（Schema驱动）">
                <Row gutter={[12, 12]}>
                  {strategyParamEntries.map((spec) => {
                    const value = strategyParamsPayload[spec.key]
                    if (spec.type === 'boolean') {
                      return (
                        <Col xs={24} md={8} key={spec.key}>
                          <Space orientation="vertical">
                            <span>{spec.title}</span>
                            <Switch
                              checked={Boolean(value)}
                              onChange={(checked) => updateStrategyParam(spec.key, checked)}
                            />
                          </Space>
                        </Col>
                      )
                    }
                    if (spec.type === 'enum') {
                      return (
                        <Col xs={24} md={8} key={spec.key}>
                          <Space orientation="vertical" style={{ width: '100%' }}>
                            <span>{spec.title}</span>
                            <Select
                              value={typeof value === 'string' ? value : undefined}
                              options={spec.options.map((item) => ({ value: item, label: item }))}
                              onChange={(next) => updateStrategyParam(spec.key, String(next))}
                              allowClear
                            />
                          </Space>
                        </Col>
                      )
                    }
                    return (
                      <Col xs={24} md={8} key={spec.key}>
                        <Space orientation="vertical" style={{ width: '100%' }}>
                          <span>{spec.title}</span>
                          <InputNumber
                            value={typeof value === 'number' ? value : undefined}
                            min={typeof spec.minimum === 'number' ? spec.minimum : undefined}
                            max={typeof spec.maximum === 'number' ? spec.maximum : undefined}
                            step={spec.type === 'integer' ? 1 : 0.1}
                            style={{ width: '100%' }}
                            onChange={(next) => {
                              if (next === null || next === undefined || Number.isNaN(Number(next))) {
                                updateStrategyParam(spec.key, undefined)
                                return
                              }
                              updateStrategyParam(spec.key, Number(next))
                            }}
                          />
                        </Space>
                      </Col>
                    )
                  })}
                </Row>
                <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
                  <Col xs={24} md={8}>
                    <Space orientation="vertical" style={{ width: '100%' }}>
                      <span>策略预设</span>
                      <Select
                        value={strategyPresetId ?? undefined}
                        placeholder="选择预设"
                        options={strategyPresets.map((item, index) => ({
                          value: item.id,
                          label: `预设#${index + 1} | ${item.name}`,
                        }))}
                        onChange={(value) => setStrategyPresetId(String(value))}
                        allowClear
                      />
                    </Space>
                  </Col>
                  <Col xs={24} md={8}>
                    <Space orientation="vertical" style={{ width: '100%' }}>
                      <span>预设名称</span>
                      <Input
                        value={strategyPresetName}
                        onChange={(event) => setStrategyPresetName(event.target.value)}
                        placeholder="输入预设名后保存"
                      />
                    </Space>
                  </Col>
                  <Col xs={24} md={8}>
                    <Space style={{ marginTop: 22 }} wrap>
                      <Button size="small" onClick={handleSaveStrategyPreset}>保存预设</Button>
                      <Button size="small" onClick={handleApplyStrategyPreset}>应用预设</Button>
                      <Button size="small" danger onClick={handleDeleteStrategyPreset}>删除预设</Button>
                    </Space>
                  </Col>
                </Row>
                {selectedStrategyPreset ? (
                  <Alert
                    style={{ marginTop: 10 }}
                    type="info"
                    showIcon
                    message={`当前预设：${selectedStrategyPreset.name}`}
                    description={`保存时间：${selectedStrategyPreset.saved_at}`}
                  />
                ) : null}
              </Card>
            </Col>
          ) : null}

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
          <Col xs={24} md={6}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <span>延迟入场天数(交易日)</span>
              <InputNumber
                min={1}
                max={5}
                value={entryDelayDays}
                onChange={(value) => setEntryDelayDays(Number(value || TRADE_BACKTEST_DEFAULTS.entryDelayDays))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical">
              <span>延迟窗口失效保护</span>
              <Switch checked={delayInvalidationEnabled} onChange={setDelayInvalidationEnabled} />
            </Space>
          </Col>
          <Col xs={24} md={6}>
            <Space orientation="vertical">
              <span>高级分析</span>
              <Switch checked={enableAdvancedAnalysis} onChange={setEnableAdvancedAnalysis} />
            </Space>
          </Col>
          <Col xs={24} md={18}>
            <Alert
              type={enableAdvancedAnalysis ? 'info' : 'warning'}
              showIcon
              title={enableAdvancedAnalysis ? '已启用高级分析' : '已关闭高级分析'}
              description={
                enableAdvancedAnalysis
                  ? '将额外计算稳定性评分、市场状态拆分、蒙特卡洛压力测试和 Walk-forward 验证，耗时会增加。'
                  : '仅执行主回测，速度更快但不生成稳定性/压力测试/样本外验证。'
              }
            />
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

      <Card title="A/B 实验（延迟/门控/语义）">
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={8}>
              <Space orientation="vertical">
                <span>自动生成默认变体</span>
                <Switch checked={abAutoGenerateDefaults} onChange={setAbAutoGenerateDefaults} />
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>最大变体数</span>
                <InputNumber
                  min={1}
                  max={64}
                  value={abMaxVariants}
                  style={{ width: '100%' }}
                  onChange={(value) => setAbMaxVariants(Math.max(1, Math.min(64, Math.round(Number(value) || 16))))}
                />
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>动作</span>
                <Button type="primary" ghost loading={runABExperimentMutation.isPending} onClick={handleRunABExperiment}>
                  运行 A/B 实验
                </Button>
              </Space>
            </Col>
            <Col xs={24}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <span>自定义变体（可选 JSON 数组）</span>
                <Input.TextArea
                  rows={3}
                  value={abCustomVariantsText}
                  onChange={(event) => setAbCustomVariantsText(event.target.value)}
                  placeholder='例如：[{"label":"delay_2","entry_delay_days":2},{"label":"v2_gate","strategy_id":"wyckoff_trend_v2"}]'
                />
              </Space>
            </Col>
          </Row>

          {abError ? <Alert type="error" showIcon message={abError} /> : null}
          {abResult ? (
            <Space wrap>
              <Tag color="geekblue">{`baseline=${abResult.baseline_variant_id || '-'}`}</Tag>
              <Tag color="success">{`best=${abResult.best_variant_id || '-'}`}</Tag>
              <Tag>{`variants=${abVariantRows.length}`}</Tag>
            </Space>
          ) : null}
          {abResult?.notes?.length ? (
            <Alert
              type="info"
              showIcon
              message="实验说明"
              description={abResult.notes.join(' ')}
            />
          ) : null}
          {abVariantRows.length > 0 ? (
            <Table
              size="small"
              rowKey={(row) => row.variant_id}
              columns={abVariantColumns}
              dataSource={abVariantRows}
              pagination={{ pageSize: 8, showSizeChanger: false }}
              scroll={{ x: 1200 }}
            />
          ) : null}
          {abComparisonRows.length > 0 ? (
            <Table
              size="small"
              rowKey={(row) => `${row.baseline_variant_id}-${row.variant_id}`}
              columns={abComparisonColumns}
              dataSource={abComparisonRows}
              pagination={{ pageSize: 8, showSizeChanger: false }}
              scroll={{ x: 920 }}
            />
          ) : null}
        </Space>
      </Card>

      <Card title="回测报告导出与共享">
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Button
              type="primary"
              ghost
              onClick={handleExportFtbt}
              disabled={!result}
              loading={exportReportMutation.isPending}
            >
              导出 ftbt
            </Button>
            <Button onClick={handleExportXlsxReport} disabled={!result}>
              导出 Excel
            </Button>
            <Button onClick={handleExportHtmlReport} disabled={!result}>
              导出 HTML
            </Button>
            <Button
              onClick={() => importReportFileRef.current?.click()}
              loading={importReportMutation.isPending}
            >
              导入 ftbt
            </Button>
            <input
              ref={importReportFileRef}
              type="file"
              accept=".ftbt"
              style={{ display: 'none' }}
              onChange={(event) => {
                const file = event.target.files?.[0]
                handleImportFtbt(file)
                event.target.value = ''
              }}
            />
            <Tag color="blue">{`已导入 ${reportLibrary.length}`}</Tag>
          </Space>
          <Space wrap style={{ width: '100%' }}>
            <Select
              style={{ minWidth: 440 }}
              placeholder={reportLibraryLoading ? '加载报告列表中...' : '选择导入报告'}
              value={selectedReportId ?? undefined}
              onChange={(value) => setSelectedReportId(String(value))}
              loading={reportLibraryLoading}
              options={reportLibrary.map((item) => ({
                value: item.report_id,
                label: `${item.report_id} | ${item.date_from}~${item.date_to} | 收益 ${formatPct(item.total_return)}`,
              }))}
            />
            <Button
              type="primary"
              onClick={handleLoadSelectedReport}
              disabled={!selectedReportId}
              loading={loadReportMutation.isPending}
            >
              加载报告
            </Button>
            <Button
              danger
              onClick={handleDeleteSelectedReport}
              disabled={!selectedReportId}
              loading={deleteReportMutation.isPending}
            >
              删除报告
            </Button>
          </Space>
          <Alert
            type="info"
            showIcon
            title="导入说明"
            description="可直接导出 Excel/HTML；.ftbt 用于跨设备共享（内含报告HTML、Excel与回测数据）。重复导入同一 report_id 将覆盖旧报告并保留导入时间。"
          />
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
            {plateauTaskStatus && (plateauTaskStatus.status === 'running' || plateauTaskStatus.status === 'pending') ? (
              <Button
                loading={controlPlateauTaskMutation.isPending && controlPlateauTaskMutation.variables?.action === 'pause'}
                onClick={() => controlPlateauTaskMutation.mutate({ action: 'pause', taskId: plateauTaskStatus.task_id })}
              >
                暂停平原任务
              </Button>
            ) : null}
            {plateauTaskStatus && plateauTaskStatus.status === 'paused' ? (
              <Button
                type="primary"
                ghost
                loading={controlPlateauTaskMutation.isPending && controlPlateauTaskMutation.variables?.action === 'resume'}
                onClick={() => controlPlateauTaskMutation.mutate({ action: 'resume', taskId: plateauTaskStatus.task_id })}
              >
                继续平原任务
              </Button>
            ) : null}
            {plateauTaskStatus
            && (plateauTaskStatus.status === 'running' || plateauTaskStatus.status === 'pending' || plateauTaskStatus.status === 'paused') ? (
              <Button
                danger
                loading={controlPlateauTaskMutation.isPending && controlPlateauTaskMutation.variables?.action === 'cancel'}
                onClick={() => controlPlateauTaskMutation.mutate({ action: 'cancel', taskId: plateauTaskStatus.task_id })}
              >
                停止平原任务
              </Button>
            ) : null}
            {plateauTaskOptions.length > 0 ? (
              <Select
                style={{ minWidth: 280 }}
                value={plateauSelectedTaskId}
                options={plateauTaskOptions}
                onChange={(value) => setSelectedPlateauTask(String(value))}
              />
            ) : null}
            {plateauTaskStatus ? (
              <Tag color={plateauTaskStatusColor(plateauTaskStatus.status)}>{plateauTaskStatusLabel(plateauTaskStatus.status)}</Tag>
            ) : null}
            {plateauTaskRunningCount > 0 ? <Tag color="processing">{`运行中 ${plateauTaskRunningCount}`}</Tag> : null}
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

      {effectivePlateauError ? <Alert type="error" title={effectivePlateauError} showIcon /> : null}

      {plateauTaskStatus ? (
        <Card title={plateauTaskRunning ? '收益平原进度' : '最近收益平原进度'}>
          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
            <Progress
              percent={Math.max(0, Math.min(100, Number(plateauTaskProgress?.percent ?? 0)))}
              status={plateauTaskRunning ? 'active' : (plateauTaskStatus.status === 'succeeded' ? 'success' : 'normal')}
            />
            <div>{plateauTaskProgress?.message || '任务执行中...'}</div>
            <div>
              进度：{plateauTaskProgress?.processed_points ?? 0} / {plateauTaskProgress?.total_points ?? 0}
            </div>
          </Space>
        </Card>
      ) : null}

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

          {plateauCorrelationRows.length > 0 ? (
            <Card title="参数相关性分析（皮尔逊）">
              <Table
                size="small"
                columns={plateauCorrelationColumns}
                dataSource={plateauCorrelationRows}
                rowKey={(row) => row.parameter}
                pagination={false}
                scroll={{ x: 760 }}
              />
            </Card>
          ) : (
            <Alert type="info" showIcon title="参数相关性分析暂不可用" description="至少需要 2 组成功参数，才能计算相关性。" />
          )}

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

          {riskMetrics ? (
            <Row gutter={[12, 12]}>
              <Col xs={12} md={6}>
                <Card>
                  <Statistic title="Sharpe" value={riskMetrics.sharpe} precision={3} />
                </Card>
              </Col>
              <Col xs={12} md={6}>
                <Card>
                  <Statistic title="Sortino" value={riskMetrics.sortino} precision={3} />
                </Card>
              </Col>
              <Col xs={12} md={6}>
                <Card>
                  <Statistic title="Calmar" value={riskMetrics.calmar} precision={3} />
                </Card>
              </Col>
              <Col xs={12} md={6}>
                <Card>
                  <Statistic title="Expectancy" value={riskMetrics.expectancy * 100} precision={2} suffix="%" />
                </Card>
              </Col>
            </Row>
          ) : (
            <Alert type="info" showIcon title="当前结果未包含风险指标。" />
          )}

          {stabilityDiagnostics ? (
            <Card title="稳定性评分">
              <Space orientation="vertical" size={10} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color="processing">{`评分 ${stabilityDiagnostics.stability_score.toFixed(3)}`}</Tag>
                  <Tag color="default">{`邻域一致性 ${stabilityDiagnostics.neighborhood_consistency.toFixed(3)}`}</Tag>
                  <Tag color="warning">{`交易数惩罚 ${stabilityDiagnostics.trade_count_penalty.toFixed(3)}`}</Tag>
                  <Tag color="warning">{`方差惩罚 ${stabilityDiagnostics.return_variance_penalty.toFixed(3)}`}</Tag>
                </Space>
                {stabilityDiagnostics.notes.length > 0 ? (
                  <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                    {stabilityDiagnostics.notes.map((note, idx) => (
                      <li key={`${idx}-${note}`}>{note}</li>
                    ))}
                  </ul>
                ) : null}
                {stabilityAdvice ? (
                  <Alert
                    type={stabilityAdvice.level}
                    showIcon
                    title={stabilityAdvice.title}
                    description={
                      stabilityAdvice.tips.length > 0 ? (
                        <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                          {stabilityAdvice.tips.map((tip, index) => (
                            <li key={`${index}-${tip}`}>{tip}</li>
                          ))}
                        </ul>
                      ) : undefined
                    }
                  />
                ) : null}
              </Space>
            </Card>
          ) : null}

          {regimeBreakdown.length > 0 ? (
            <Card title="市场状态拆分（代理）">
              <Space orientation="vertical" size={10} style={{ width: '100%' }}>
                <Table
                  size="small"
                  columns={regimeColumns}
                  dataSource={regimeBreakdown}
                  rowKey={(row) => row.regime}
                  pagination={false}
                  scroll={{ x: 760 }}
                />
                {regimeAdvice ? (
                  <Alert
                    type={regimeAdvice.level}
                    showIcon
                    title={regimeAdvice.title}
                    description={
                      regimeAdvice.tips.length > 0 ? (
                        <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                          {regimeAdvice.tips.map((tip, index) => (
                            <li key={`${index}-${tip}`}>{tip}</li>
                          ))}
                        </ul>
                      ) : undefined
                    }
                  />
                ) : null}
              </Space>
            </Card>
          ) : null}

          {monteCarlo ? (
            <Card title="蒙特卡洛压力测试">
              <Space orientation="vertical" size={10} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color="geekblue">{`模拟次数 ${monteCarlo.simulations}`}</Tag>
                  <Tag>{`收益 P5/P50/P95 ${formatPct(monteCarlo.total_return_p5)} / ${formatPct(monteCarlo.total_return_p50)} / ${formatPct(monteCarlo.total_return_p95)}`}</Tag>
                  <Tag>{`回撤 P5/P50/P95 ${formatPct(monteCarlo.max_drawdown_p5)} / ${formatPct(monteCarlo.max_drawdown_p50)} / ${formatPct(monteCarlo.max_drawdown_p95)}`}</Tag>
                  <Tag color="red">{`极端亏损概率 ${(monteCarlo.ruin_probability * 100).toFixed(2)}%`}</Tag>
                </Space>
                {monteCarloAdvice ? (
                  <Alert
                    type={monteCarloAdvice.level}
                    showIcon
                    title={monteCarloAdvice.title}
                    description={
                      monteCarloAdvice.tips.length > 0 ? (
                        <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                          {monteCarloAdvice.tips.map((tip, index) => (
                            <li key={`${index}-${tip}`}>{tip}</li>
                          ))}
                        </ul>
                      ) : undefined
                    }
                  />
                ) : null}
              </Space>
            </Card>
          ) : null}

          {walkForward ? (
            <Card title="Walk-forward 验证">
              <Space orientation="vertical" size={10} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color="processing">{`folds ${walkForward.fold_count}`}</Tag>
                  <Tag>{`候选参数 ${walkForward.candidate_count}`}</Tag>
                  <Tag color="green">{`OOS通过率 ${(walkForward.oos_pass_rate * 100).toFixed(2)}%`}</Tag>
                  <Tag>{`测试均值收益 ${formatPct(walkForward.avg_test_return)}`}</Tag>
                  <Tag>{`测试均值胜率 ${formatPct(walkForward.avg_test_win_rate)}`}</Tag>
                </Space>
                {walkForward.folds.length > 0 ? (
                  <Table
                    size="small"
                    columns={walkForwardColumns}
                    dataSource={walkForward.folds}
                    rowKey={(row) => `${row.fold_index}-${row.train_date_from}-${row.test_date_from}`}
                    pagination={false}
                    scroll={{ x: 1400 }}
                  />
                ) : null}
                {walkForward.notes.length > 0 ? (
                  <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                    {walkForward.notes.map((note, idx) => (
                      <li key={`${idx}-${note}`}>{note}</li>
                    ))}
                  </ul>
                ) : null}
                {walkForwardAdvice ? (
                  <Alert
                    type={walkForwardAdvice.level}
                    showIcon
                    title={walkForwardAdvice.title}
                    description={
                      walkForwardAdvice.tips.length > 0 ? (
                        <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                          {walkForwardAdvice.tips.map((tip, index) => (
                            <li key={`${index}-${tip}`}>{tip}</li>
                          ))}
                        </ul>
                      ) : undefined
                    }
                  />
                ) : null}
              </Space>
            </Card>
          ) : null}

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
