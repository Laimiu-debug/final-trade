import ReactECharts from 'echarts-for-react'
import type { CandlePoint, SignalResult, SignalType } from '@/types/contracts'
import { movingAverage } from '@/shared/utils/chart'
import { resolveNearestTradingDateIndex } from '@/shared/utils/candleStats'

interface KLineChartProps {
  candles: CandlePoint[]
  signals?: SignalResult[]
  manualStartDate?: string
  aiBreakoutDate?: string
  statsRangeStartDate?: string
  statsRangeEndDate?: string
  onCandleDoubleClick?: (date: string) => void
}

interface MarkPointRecord {
  name: string
  coord: [string, number]
  value: string
  symbol?: string
  symbolSize?: number
  symbolOffset?: [number, number]
  tooltipText?: string
  itemStyle: {
    color: string
  }
}

interface MarkPointDraft extends MarkPointRecord {
  dateKey: string
}

type EventCategory = 'accumulation' | 'distributionRisk' | 'other'
type PhaseLegendType = 'accumulation' | 'distribution' | 'unknown'

interface EventPointRecord {
  value: [string, number]
  eventCode: string
  tooltipText: string
  symbolOffset?: [number, number]
  itemStyle: {
    color: string
  }
}

interface EventPointDraft extends EventPointRecord {
  dateKey: string
  category: EventCategory
  anchor: 'high' | 'low'
}

type StageRangeItem = [
  {
    name: string
    xAxis: string
    itemStyle: { color: string }
    label: { show: boolean; formatter: string; color: string; fontSize: number }
  },
  {
    xAxis: string
  },
]

interface AxisTooltipParam {
  seriesName?: string
  axisValue?: string
  dataIndex?: number
}

const WYCKOFF_EVENT_DISPLAY_MAP: Record<string, string> = {
  PS: 'PS Initial Support',
  SC: 'SC Selling Climax',
  AR: 'AR Automatic Rally',
  ST: 'ST Secondary Test',
  TSO: 'TSO Terminal Shakeout',
  SPRING: 'Spring',
  SOS: 'SOS Sign of Strength',
  JOC: 'JOC Jump Across Creek',
  LPS: 'LPS Last Point of Support',
  PSY: 'PSY Preliminary Supply',
  BC: 'BC Buying Climax',
  'AR(D)': 'AR(d) Auto Reaction',
  'ST(D)': 'ST(d) Secondary Test',
  UTAD: 'UTAD Upthrust After Distribution',
  SOW: 'SOW Sign of Weakness',
  LPSY: 'LPSY Last Point of Supply',
}

const WYCKOFF_EVENT_GUIDE = {
  accumulation: ['PS', 'SC', 'AR', 'ST', 'TSO', 'Spring', 'SOS', 'JOC', 'LPS'],
  risk: ['PSY', 'BC', 'AR(d)', 'ST(d)', 'UTAD', 'SOW', 'LPSY'],
}

const WYCKOFF_EVENT_CN_MAP: Record<string, string> = {
  PS: '\u521d\u59cb\u652f\u6491',
  SC: '\u5356\u51fa\u9ad8\u6f6e',
  AR: '\u81ea\u52a8\u53cd\u5f39',
  ST: '\u4e8c\u6b21\u6d4b\u8bd5',
  TSO: '\u672b\u7aef\u9707\u4ed3',
  SPRING: '\u5f39\u7c27\u6d4b\u8bd5',
  SOS: '\u5f3a\u52bf\u4fe1\u53f7',
  JOC: '\u8dc3\u8fc7\u5c0f\u6eaa',
  LPS: '\u6700\u540e\u652f\u6491\u70b9',
  PSY: '\u521d\u59cb\u4f9b\u7ed9',
  BC: '\u4e70\u5165\u9ad8\u6f6e',
  'AR(D)': '\u81ea\u52a8\u56de\u843d',
  'ST(D)': '\u6d3e\u53d1\u4e8c\u6d4b',
  UTAD: '\u6d3e\u53d1\u540e\u4e0a\u51b2',
  SOW: '\u5f31\u52bf\u4fe1\u53f7',
  LPSY: '\u6700\u540e\u4f9b\u7ed9\u70b9',
}

type LegendSymbol = 'line' | 'bar' | 'triangle' | 'diamond' | 'circle' | 'pill' | 'pin' | 'area'

interface LegendItem {
  label: string
  color: string
  symbol: LegendSymbol
}

function renderLegendMarker(symbol: LegendSymbol, color: string) {
  if (symbol === 'line') {
    return <span style={{ width: 14, borderTop: `2px solid ${color}`, display: 'inline-block' }} />
  }
  if (symbol === 'bar') {
    return <span style={{ width: 12, height: 10, borderRadius: 3, background: color, display: 'inline-block' }} />
  }
  if (symbol === 'triangle') {
    return (
      <span
        style={{
          width: 0,
          height: 0,
          borderLeft: '6px solid transparent',
          borderRight: '6px solid transparent',
          borderBottom: `10px solid ${color}`,
          display: 'inline-block',
        }}
      />
    )
  }
  if (symbol === 'diamond') {
    return <span style={{ width: 10, height: 10, background: color, transform: 'rotate(45deg)', display: 'inline-block' }} />
  }
  if (symbol === 'circle') {
    return <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
  }
  if (symbol === 'pin') {
    return <span style={{ width: 10, height: 10, borderRadius: 5, background: color, display: 'inline-block' }} />
  }
  if (symbol === 'area') {
    return <span style={{ width: 12, height: 10, borderRadius: 2, background: color, display: 'inline-block' }} />
  }
  return <span style={{ width: 12, height: 10, borderRadius: 4, background: color, display: 'inline-block' }} />
}

function resolveSignalColor(signal: SignalType) {
  if (signal === 'B') return '#eb8f34'
  if (signal === 'A') return '#1677ff'
  return '#7f8c8d'
}

function resolveSignalShape(signal: SignalType) {
  if (signal === 'B') return 'triangle'
  if (signal === 'A') return 'diamond'
  return 'circle'
}

function normalizeEventCode(event: string) {
  return event.trim().replace(/\s+/g, '').toUpperCase()
}

function formatEventGuideWithZh(codes: string[]) {
  return codes
    .map((code) => {
      const label = WYCKOFF_EVENT_CN_MAP[normalizeEventCode(code)]
      return label ? `${code}(${label})` : code
    })
    .join(' / ')
}

function resolveEventCategory(eventCode: string): EventCategory {
  const normalized = normalizeEventCode(eventCode)
  const accumulationEvents = new Set(['PS', 'SC', 'AR', 'ST', 'TSO', 'SPRING', 'SOS', 'JOC', 'LPS'])
  const distributionRiskEvents = new Set(['UTAD', 'SOW', 'LPSY', 'PSY', 'BC', 'AR(D)', 'ST(D)'])
  if (accumulationEvents.has(normalized)) return 'accumulation'
  if (distributionRiskEvents.has(normalized)) return 'distributionRisk'
  return 'other'
}

function resolveEventColor(category: EventCategory) {
  if (category === 'accumulation') return '#13c2c2'
  if (category === 'distributionRisk') return '#f5222d'
  return '#8c8c8c'
}

function resolveEventDisplayName(eventCode: string) {
  const normalized = normalizeEventCode(eventCode)
  return WYCKOFF_EVENT_DISPLAY_MAP[normalized] ?? eventCode
}

function resolvePhaseLegendType(phase: string): PhaseLegendType {
  const normalized = phase.toLowerCase()
  if (phase.includes('\u5438\u7b79') || normalized.includes('accum')) return 'accumulation'
  if (phase.includes('\u6d3e\u53d1') || normalized.includes('distrib')) return 'distribution'
  return 'unknown'
}

function resolvePhaseAreaColor(phase: string) {
  const phaseType = resolvePhaseLegendType(phase)
  if (phaseType === 'accumulation') return 'rgba(22, 119, 255, 0.10)'
  if (phaseType === 'distribution') return 'rgba(245, 34, 45, 0.10)'
  return 'rgba(120, 136, 153, 0.08)'
}

function toPrice(value: number) {
  if (!Number.isFinite(value)) return '--'
  return value.toFixed(2)
}

function toLargeNumber(value: number) {
  if (!Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs >= 100000000) return `${(value / 100000000).toFixed(2)}\u4ebf`
  if (abs >= 10000) return `${(value / 10000).toFixed(2)}\u4e07`
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function toSignedNumber(value: number, digits = 2) {
  if (!Number.isFinite(value)) return '--'
  if (value > 0) return `+${value.toFixed(digits)}`
  return value.toFixed(digits)
}

function toSignedPercent(value: number, digits = 2) {
  if (!Number.isFinite(value)) return '--'
  const pct = value * 100
  if (pct > 0) return `+${pct.toFixed(digits)}%`
  return `${pct.toFixed(digits)}%`
}

function toMaybeNumber(value: number | '-' | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return value.toFixed(2)
}

function buildStackOffsetsAbove(count: number) {
  if (count <= 1) return [-24]
  const step = 10
  const base = -30
  return Array.from({ length: count }, (_, index) => base + index * step)
}

function buildStackOffsetsBelow(count: number) {
  if (count <= 1) return [26]
  const step = 10
  const base = 30
  return Array.from({ length: count }, (_, index) => base + index * step)
}

function toStackedMarkPoints(points: MarkPointDraft[]) {
  const grouped = new Map<string, MarkPointDraft[]>()
  for (const point of points) {
    const existed = grouped.get(point.dateKey)
    if (existed) {
      existed.push(point)
    } else {
      grouped.set(point.dateKey, [point])
    }
  }

  const stacked: MarkPointRecord[] = []
  for (const group of grouped.values()) {
    const offsets = buildStackOffsetsAbove(group.length)
    group.forEach((point, index) => {
      const { dateKey: _dateKey, ...rest } = point
      stacked.push({
        ...rest,
        symbolOffset: [0, offsets[index]],
      })
    })
  }
  return stacked
}

function toStackedEventPoints(points: EventPointDraft[]) {
  const grouped = new Map<string, EventPointDraft[]>()
  for (const point of points) {
    const groupKey = `${point.dateKey}|${point.anchor}`
    const existed = grouped.get(groupKey)
    if (existed) {
      existed.push(point)
    } else {
      grouped.set(groupKey, [point])
    }
  }

  const byCategory: Record<EventCategory, EventPointRecord[]> = {
    accumulation: [],
    distributionRisk: [],
    other: [],
  }

  for (const group of grouped.values()) {
    const anchor = group[0].anchor
    const offsets = anchor === 'high' ? buildStackOffsetsAbove(group.length) : buildStackOffsetsBelow(group.length)
    group.forEach((point, index) => {
      const { dateKey: _dateKey, category, anchor: _anchor, ...rest } = point
      byCategory[category].push({
        ...rest,
        symbolOffset: [0, offsets[index]],
      })
    })
  }

  return byCategory
}

function resolveDateMarkLine(date: string | undefined, xData: string[], name: string, color: string) {
  if (!date) return null
  const index = resolveNearestTradingDateIndex(date, xData)
  if (index < 0) return null
  const mappedDate = xData[index]
  const mappedSuffix = mappedDate === date ? '' : `\uff08\u6620\u5c04\u5230 ${mappedDate}\uff09`
  return {
    name,
    xAxis: mappedDate,
    lineStyle: { color, width: 1.4 },
    label: { formatter: `${name}${mappedSuffix}` },
  }
}

export function KLineChart({
  candles,
  signals = [],
  manualStartDate,
  aiBreakoutDate,
  statsRangeStartDate,
  statsRangeEndDate,
  onCandleDoubleClick,
}: KLineChartProps) {
  const xData = candles.map((item) => item.time)
  const candleData = candles.map((item) => [item.open, item.close, item.low, item.high])
  const volumes = candles.map((item) => item.volume)
  const ma5 = movingAverage(candles, 5)
  const ma10 = movingAverage(candles, 10)
  const ma20 = movingAverage(candles, 20)

  const markPointDrafts: MarkPointDraft[] = []
  const eventPointDrafts: EventPointDraft[] = []
  const stageRangeSet = new Set<string>()
  const stageRangeData: StageRangeItem[] = []
  const signalSummaryByDate = new Map<string, string[]>()
  const phaseLegendFlags = {
    accumulation: false,
    distribution: false,
    unknown: false,
    stats: false,
  }
  const unknownEventCodeSet = new Set<string>()
  const unknownPhaseNameSet = new Set<string>()

  for (const signal of signals) {
    const triggerIndex = resolveNearestTradingDateIndex(signal.trigger_date, xData)
    if (triggerIndex < 0) continue

    const mappedTriggerDate = xData[triggerIndex]
    const mappedHint = mappedTriggerDate === signal.trigger_date ? '' : ` -> ${mappedTriggerDate}`
    const phase = signal.wyckoff_phase?.trim() || '\u9636\u6bb5\u672a\u660e'
    const event = signal.wyckoff_signal?.trim() || signal.wy_events?.[signal.wy_events.length - 1] || '\u65e0\u4e8b\u4ef6'
    const normalizedEventDateMap = new Map<string, string>()
    Object.entries(signal.wy_event_dates ?? {}).forEach(([eventCode, eventDate]) => {
      const normalizedCode = normalizeEventCode(eventCode)
      const normalizedDate = typeof eventDate === 'string' ? eventDate.trim() : ''
      if (!normalizedCode || !normalizedDate) return
      normalizedEventDateMap.set(normalizedCode, normalizedDate)
    })
    const eventNodes: Array<{ eventCode: string; eventDate: string; category: EventCategory }> = []
    if (Array.isArray(signal.wy_event_chain)) {
      for (const node of signal.wy_event_chain) {
        const eventCode = typeof node?.event === 'string' ? node.event.trim() : ''
        const eventDate = typeof node?.date === 'string' ? node.date.trim() : ''
        if (!eventCode || !eventDate) continue
        const category =
          node.category === 'accumulation' || node.category === 'distributionRisk' || node.category === 'other'
            ? node.category
            : resolveEventCategory(eventCode)
        eventNodes.push({
          eventCode,
          eventDate,
          category,
        })
      }
    }
    if (eventNodes.length === 0) {
      const rawEventList = [
        ...Object.keys(signal.wy_event_dates ?? {}),
        ...(signal.wy_events ?? []),
        ...(signal.wy_risk_events ?? []),
        signal.wyckoff_signal,
      ]
        .map((item) => (item ?? '').trim())
        .filter((item) => item.length > 0)
      const fallbackKeySet = new Set<string>()
      for (const eventCode of rawEventList) {
        const normalizedCode = normalizeEventCode(eventCode)
        if (!normalizedCode) continue
        const eventDateSource = normalizedEventDateMap.get(normalizedCode) || signal.trigger_date
        const category = resolveEventCategory(eventCode)
        const dedupKey = `${normalizedCode}|${eventDateSource}|${category}`
        if (fallbackKeySet.has(dedupKey)) continue
        fallbackKeySet.add(dedupKey)
        eventNodes.push({
          eventCode,
          eventDate: eventDateSource,
          category,
        })
      }
    }

    const signalType = signal.primary_signal
    const triggerSummaryEntry = `${signalType}\u4e3b\u4fe1\u53f7 | ${phase} | \u89e6\u53d1:${signal.trigger_date}${mappedHint}`
    const existedTriggerSummary = signalSummaryByDate.get(mappedTriggerDate)
    if (existedTriggerSummary) {
      existedTriggerSummary.push(triggerSummaryEntry)
    } else {
      signalSummaryByDate.set(mappedTriggerDate, [triggerSummaryEntry])
    }

    const eventTimelineIndexes: number[] = []
    eventNodes.forEach(({ eventCode, eventDate, category }) => {
      const eventDateSource = eventDate || signal.trigger_date
      const eventIndex = resolveNearestTradingDateIndex(eventDateSource, xData)
      if (eventIndex < 0) return
      const mappedEventDate = xData[eventIndex]
      const mappedEventHint = mappedEventDate === eventDateSource ? '' : ` -> ${mappedEventDate}`
      eventTimelineIndexes.push(eventIndex)

      const anchor = category === 'distributionRisk' ? 'high' : 'low'
      const anchorPrice = anchor === 'high' ? candles[eventIndex].high : candles[eventIndex].low
      const eventDisplayName = resolveEventDisplayName(eventCode)
      eventPointDrafts.push({
        dateKey: mappedEventDate,
        category,
        anchor,
        value: [mappedEventDate, anchorPrice],
        eventCode,
        tooltipText: `\u4e8b\u4ef6:${eventDisplayName} | \u9636\u6bb5:${phase} | \u4e8b\u4ef6\u65e5:${eventDateSource}${mappedEventHint}`,
        itemStyle: {
          color: resolveEventColor(category),
        },
      })
      if (category === 'other') {
        unknownEventCodeSet.add(eventCode)
      }

      const summaryEntry = `${signalType} | ${phase} | \u4e8b\u4ef6:${eventDisplayName}`
      const existedSummary = signalSummaryByDate.get(mappedEventDate)
      if (existedSummary) {
        existedSummary.push(summaryEntry)
      } else {
        signalSummaryByDate.set(mappedEventDate, [summaryEntry])
      }
    })

    markPointDrafts.push({
      dateKey: mappedTriggerDate,
      name: `${signalType}\u4e3b\u4fe1\u53f7`,
      coord: [mappedTriggerDate, candles[triggerIndex].high],
      value: signalType,
      symbol: resolveSignalShape(signalType),
      symbolSize: 16,
      tooltipText: `${signalType}\u4e3b\u4fe1\u53f7 | \u9636\u6bb5:${phase} | \u4e8b\u4ef6:${event} | \u89e6\u53d1:${signal.trigger_date}${mappedHint}`,
      itemStyle: {
        color: resolveSignalColor(signalType),
      },
    })

    if (eventNodes.length === 0) {
      const fallbackSummaryEntry = `${signalType} | ${phase} | \u4e8b\u4ef6:${event}`
      const existedSummary = signalSummaryByDate.get(mappedTriggerDate)
      if (existedSummary) {
        existedSummary.push(fallbackSummaryEntry)
      } else {
        signalSummaryByDate.set(mappedTriggerDate, [fallbackSummaryEntry])
      }
    }

    const stageTimelineIndexes = eventTimelineIndexes.length > 0 ? eventTimelineIndexes : [triggerIndex]
    const rangeStart = xData[Math.min(...stageTimelineIndexes)]
    const rangeEnd = xData[Math.max(...stageTimelineIndexes)]
    const rangeKey = `${phase}|${rangeStart}|${rangeEnd}`
    if (!stageRangeSet.has(rangeKey)) {
      stageRangeSet.add(rangeKey)
      const phaseType = resolvePhaseLegendType(phase)
      phaseLegendFlags[phaseType] = true
      if (phaseType === 'unknown') {
        unknownPhaseNameSet.add(phase)
      }
      stageRangeData.push([
        {
          name: `\u9636\u6bb5:${phase}`,
          xAxis: rangeStart,
          itemStyle: { color: resolvePhaseAreaColor(phase) },
          label: {
            show: false,
            formatter: phase,
            color: '#2f5452',
            fontSize: 11,
          },
        },
        {
          xAxis: rangeEnd,
        },
      ])
    }
  }

  if (statsRangeStartDate && statsRangeEndDate && xData.length > 0) {
    const rangeStartIndex = resolveNearestTradingDateIndex(statsRangeStartDate, xData)
    const rangeEndIndex = resolveNearestTradingDateIndex(statsRangeEndDate, xData)
    if (rangeStartIndex >= 0 && rangeEndIndex >= 0) {
      const left = Math.min(rangeStartIndex, rangeEndIndex)
      const right = Math.max(rangeStartIndex, rangeEndIndex)
      phaseLegendFlags.stats = true
      stageRangeData.push([
        {
          name: '\u7edf\u8ba1\u533a\u95f4',
          xAxis: xData[left],
          itemStyle: { color: 'rgba(250, 173, 20, 0.12)' },
          label: {
            show: false,
            formatter: '\u7edf\u8ba1\u533a\u95f4',
            color: '#8a5a00',
            fontSize: 11,
          },
        },
        {
          xAxis: xData[right],
        },
      ])
    }
  }

  function makeDateMarkPoint(
    date: string | undefined,
    label: string,
    type: 'high' | 'low',
    color: string,
  ): MarkPointDraft | null {
    if (!date) return null
    const index = resolveNearestTradingDateIndex(date, xData)
    if (index < 0) return null
    const mappedDate = xData[index]
    return {
      dateKey: mappedDate,
      name: label,
      coord: [mappedDate, type === 'high' ? candles[index].high : candles[index].low],
      value: label,
      symbol: 'pin',
      symbolSize: 14,
      tooltipText: `${label}: ${date}${mappedDate === date ? '' : ` -> ${mappedDate}`}`,
      itemStyle: { color },
    }
  }

  const manualPoint = makeDateMarkPoint(manualStartDate, '\u4eba\u5de5\u542f\u52a8\u65e5', 'low', '#13c2c2')
  if (manualPoint) {
    markPointDrafts.push(manualPoint)
  }
  const aiPoint = makeDateMarkPoint(aiBreakoutDate, 'AI\u8d77\u7206\u65e5', 'high', '#fa8c16')
  if (aiPoint) {
    markPointDrafts.push(aiPoint)
  }

  const allMarkPoints = toStackedMarkPoints(markPointDrafts)
  const eventPointsByCategory = toStackedEventPoints(eventPointDrafts)
  const unknownEventCodes = Array.from(unknownEventCodeSet).sort((a, b) => a.localeCompare(b, 'zh-CN'))
  const unknownPhaseNames = Array.from(unknownPhaseNameSet).sort((a, b) => a.localeCompare(b, 'zh-CN'))

  const markLineData = [
    resolveDateMarkLine(manualStartDate, xData, '\u4eba\u5de5\u542f\u52a8\u65e5', '#13c2c2'),
    resolveDateMarkLine(aiBreakoutDate, xData, 'AI\u8d77\u7206\u65e5', '#fa8c16'),
  ].filter(Boolean)
  const primaryLegendItems: LegendItem[] = [
    { label: '\u65e5K', color: '#ce5649', symbol: 'line' },
    { label: 'MA5', color: '#e88e1a', symbol: 'line' },
    { label: 'MA10', color: '#0f8b6f', symbol: 'line' },
    { label: 'MA20', color: '#3160db', symbol: 'line' },
    { label: '\u6210\u4ea4\u91cf', color: '#8ca9a7', symbol: 'bar' },
    { label: 'B\u4fe1\u53f7', color: '#eb8f34', symbol: 'triangle' },
    { label: 'A\u4fe1\u53f7', color: '#1677ff', symbol: 'diamond' },
    { label: 'C\u4fe1\u53f7', color: '#7f8c8d', symbol: 'circle' },
  ]
  const annotationLegendItems: LegendItem[] = []
  if (eventPointsByCategory.accumulation.length > 0) {
    annotationLegendItems.push({ label: '\u5438\u7b79\u4e8b\u4ef6', color: '#13c2c2', symbol: 'pill' })
  }
  if (eventPointsByCategory.distributionRisk.length > 0) {
    annotationLegendItems.push({ label: '\u6d3e\u53d1/\u98ce\u9669\u4e8b\u4ef6', color: '#f5222d', symbol: 'pill' })
  }
  if (eventPointsByCategory.other.length > 0) {
    const unknownLabel = unknownEventCodes.length > 0
      ? `\u672a\u5f52\u7c7b\u4e8b\u4ef6(${unknownEventCodes.slice(0, 4).join('/')}${unknownEventCodes.length > 4 ? '...' : ''})`
      : '\u672a\u5f52\u7c7b\u4e8b\u4ef6(\u7f3a\u5c11\u4e8b\u4ef6\u4ee3\u7801\u6620\u5c04)'
    annotationLegendItems.push({ label: unknownLabel, color: '#8c8c8c', symbol: 'pill' })
  }
  if (manualPoint) {
    annotationLegendItems.push({ label: '\u4eba\u5de5\u542f\u52a8\u65e5', color: '#13c2c2', symbol: 'pin' })
  }
  if (aiPoint) {
    annotationLegendItems.push({ label: 'AI\u8d77\u7206\u65e5', color: '#fa8c16', symbol: 'pin' })
  }
  if (phaseLegendFlags.accumulation) {
    annotationLegendItems.push({ label: '\u5438\u7b79\u9636\u6bb5\u533a\u95f4', color: 'rgba(22, 119, 255, 0.50)', symbol: 'area' })
  }
  if (phaseLegendFlags.distribution) {
    annotationLegendItems.push({ label: '\u6d3e\u53d1\u9636\u6bb5\u533a\u95f4', color: 'rgba(245, 34, 45, 0.50)', symbol: 'area' })
  }
  if (phaseLegendFlags.unknown) {
    const unknownPhaseLabel = unknownPhaseNames.length > 0
      ? `\u9636\u6bb5\u5f85\u5224\u5b9a\u533a\u95f4(${unknownPhaseNames.slice(0, 2).join('/')}${unknownPhaseNames.length > 2 ? '...' : ''})`
      : '\u9636\u6bb5\u5f85\u5224\u5b9a\u533a\u95f4(\u539f\u59cb\u9636\u6bb5\u503c\u672a\u5f52\u7c7b)'
    annotationLegendItems.push({ label: unknownPhaseLabel, color: 'rgba(120, 136, 153, 0.50)', symbol: 'area' })
  }
  if (phaseLegendFlags.stats) {
    annotationLegendItems.push({ label: '\u7edf\u8ba1\u533a\u95f4', color: 'rgba(250, 173, 20, 0.50)', symbol: 'area' })
  }

  const option = {
    animation: true,
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      formatter: (rawParams: AxisTooltipParam | AxisTooltipParam[]) => {
        const params = Array.isArray(rawParams) ? rawParams : [rawParams]
        const candleParam = params.find((item) => item.seriesName === '\u65e5K')
        const dataIndex = candleParam?.dataIndex ?? -1
        if (dataIndex < 0 || dataIndex >= candles.length) return ''

        const candle = candles[dataIndex]
        const prevClose = dataIndex > 0 ? candles[dataIndex - 1].close : candle.open
        const change = candle.close - prevClose
        const changePct = prevClose > 0 ? change / prevClose : 0
        const amplitudePct = prevClose > 0 ? (candle.high - candle.low) / prevClose : 0
        const bodyPct = candle.open > 0 ? Math.abs(candle.close - candle.open) / candle.open : 0
        const upperShadow = candle.high - Math.max(candle.open, candle.close)
        const lowerShadow = Math.min(candle.open, candle.close) - candle.low

        const lookback = Math.min(5, dataIndex + 1)
        let volume5Avg = 0
        for (let i = dataIndex - lookback + 1; i <= dataIndex; i += 1) {
          volume5Avg += candles[i].volume
        }
        volume5Avg /= Math.max(lookback, 1)
        const volumeRatio = volume5Avg > 0 ? candle.volume / volume5Avg : 0

        const changeColor = change >= 0 ? '#ce5649' : '#1a8b66'
        const ma5Value = ma5[dataIndex]
        const ma10Value = ma10[dataIndex]
        const ma20Value = ma20[dataIndex]
        const signalSummary = signalSummaryByDate.get(candle.time) ?? []

        const lines = [
          `<div style="min-width: 280px">`,
          `<div style="font-weight: 600; margin-bottom: 6px">${candle.time}</div>`,
          `<div>\u5f00\u76d8\uff1a${toPrice(candle.open)}\u3000\u6536\u76d8\uff1a${toPrice(candle.close)}</div>`,
          `<div>\u6700\u9ad8\uff1a${toPrice(candle.high)}\u3000\u6700\u4f4e\uff1a${toPrice(candle.low)}</div>`,
          `<div>\u6da8\u8dcc\uff1a<span style="color:${changeColor};font-weight:600">${toSignedNumber(change)} (${toSignedPercent(changePct)})</span></div>`,
          `<div>\u632f\u5e45\uff1a${toSignedPercent(amplitudePct)}\u3000\u5b9e\u4f53\uff1a${toSignedPercent(bodyPct)}</div>`,
          `<div>\u4e0a\u5f71\uff1a${toPrice(upperShadow)}\u3000\u4e0b\u5f71\uff1a${toPrice(lowerShadow)}</div>`,
          `<div>\u6210\u4ea4\u91cf\uff1a${toLargeNumber(candle.volume)}\uff08\u91cf\u6bd45\u65e5\uff1a${volumeRatio.toFixed(2)}\uff09</div>`,
          `<div>\u6210\u4ea4\u989d\uff1a${toLargeNumber(candle.amount)}</div>`,
          `<div>\u5747\u7ebf\uff1aMA5 ${toMaybeNumber(ma5Value)} / MA10 ${toMaybeNumber(ma10Value)} / MA20 ${toMaybeNumber(ma20Value)}</div>`,
        ]

        if (signalSummary.length > 0) {
          lines.push(`<div style="margin-top: 4px">\u5a01\u79d1\u592b\uff1a${signalSummary.join('\uff1b')}</div>`)
        }

        lines.push('</div>')
        return lines.join('')
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: [0, 1] }],
      label: {
        backgroundColor: '#65706f',
      },
    },
    grid: [
      { left: '6%', right: '5%', top: '15%', height: '53%' },
      { left: '6%', right: '5%', top: '74%', height: '18%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: xData,
        scale: true,
        boundaryGap: false,
        axisLine: { onZero: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: xData,
        scale: true,
        boundaryGap: false,
        axisLine: { onZero: false },
        axisLabel: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitLine: {
          lineStyle: { color: 'rgba(31,49,48,0.14)' },
        },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { show: true, xAxisIndex: [0, 1], type: 'slider', top: '94%', start: 60, end: 100 },
    ],
    series: [
      {
        name: '\u65e5K',
        type: 'candlestick',
        data: candleData,
        itemStyle: {
          color: '#ce5649',
          color0: '#1a8b66',
          borderColor: '#ce5649',
          borderColor0: '#1a8b66',
        },
        markPoint: {
          symbolSize: 16,
          label: {
            show: false,
          },
          tooltip: {
            formatter: (params: { data?: { tooltipText?: string }; name?: string }) =>
              params.data?.tooltipText ?? params.name ?? '',
          },
          data: allMarkPoints,
        },
        markArea: {
          silent: true,
          data: stageRangeData,
        },
        markLine: {
          symbol: ['none', 'none'],
          animation: false,
          label: {
            color: '#2f5452',
            backgroundColor: 'rgba(255,255,255,0.7)',
            padding: [2, 6],
          },
          data: markLineData,
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#e88e1a' },
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#0f8b6f' },
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#3160db' },
      },
      {
        name: '\u6210\u4ea4\u91cf',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: '#8ca9a7',
        },
      },
      {
        name: '\u5438\u7b79\u4e8b\u4ef6',
        type: 'scatter',
        clip: false,
        symbol: 'roundRect',
        symbolSize: 12,
        data: eventPointsByCategory.accumulation,
        label: {
          show: true,
          fontSize: 9,
          color: '#0f5f59',
          formatter: (params: { data?: { eventCode?: string } }) => params.data?.eventCode ?? '',
        },
        labelLayout: { hideOverlap: false },
        tooltip: {
          formatter: (params: { data?: { tooltipText?: string } }) => params.data?.tooltipText ?? '',
        },
        itemStyle: { color: '#13c2c2' },
        z: 6,
      },
      {
        name: '\u98ce\u9669\u4e8b\u4ef6',
        type: 'scatter',
        clip: false,
        symbol: 'roundRect',
        symbolSize: 12,
        data: eventPointsByCategory.distributionRisk,
        label: {
          show: true,
          fontSize: 9,
          color: '#9f1239',
          formatter: (params: { data?: { eventCode?: string } }) => params.data?.eventCode ?? '',
        },
        labelLayout: { hideOverlap: false },
        tooltip: {
          formatter: (params: { data?: { tooltipText?: string } }) => params.data?.tooltipText ?? '',
        },
        itemStyle: { color: '#f5222d' },
        z: 6,
      },
      {
        name: '\u5176\u4ed6\u4e8b\u4ef6',
        type: 'scatter',
        clip: false,
        symbol: 'roundRect',
        symbolSize: 12,
        data: eventPointsByCategory.other,
        label: {
          show: true,
          fontSize: 9,
          color: '#4b5563',
          formatter: (params: { data?: { eventCode?: string } }) => params.data?.eventCode ?? '',
        },
        labelLayout: { hideOverlap: false },
        tooltip: {
          formatter: (params: { data?: { tooltipText?: string } }) => params.data?.tooltipText ?? '',
        },
        itemStyle: { color: '#8c8c8c' },
        z: 6,
      },
      {
        name: 'B\u4fe1\u53f7',
        type: 'scatter',
        data: [],
        symbol: 'triangle',
        symbolSize: 10,
        itemStyle: { color: '#eb8f34' },
      },
      {
        name: 'A\u4fe1\u53f7',
        type: 'scatter',
        data: [],
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color: '#1677ff' },
      },
      {
        name: 'C\u4fe1\u53f7',
        type: 'scatter',
        data: [],
        symbol: 'circle',
        symbolSize: 10,
        itemStyle: { color: '#7f8c8d' },
      },
      {
        name: '\u4eba\u5de5\u542f\u52a8\u65e5',
        type: 'scatter',
        data: [],
        symbol: 'pin',
        symbolSize: 10,
        itemStyle: { color: '#13c2c2' },
      },
      {
        name: 'AI\u8d77\u7206\u65e5',
        type: 'scatter',
        data: [],
        symbol: 'pin',
        symbolSize: 10,
        itemStyle: { color: '#fa8c16' },
      },
      {
        name: '\u5438\u7b79\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(22, 119, 255, 0.50)' },
      },
      {
        name: '\u6d3e\u53d1\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(245, 34, 45, 0.50)' },
      },
      {
        name: '\u672a\u660e\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(120, 136, 153, 0.50)' },
      },
      {
        name: '\u7edf\u8ba1\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(250, 173, 20, 0.50)' },
      },
    ],
  }

  const onEvents = onCandleDoubleClick
    ? {
        dblclick: (params: { name?: string; componentType?: string; seriesType?: string }) => {
          const clickedDate = typeof params?.name === 'string' ? params.name : ''
          if (!clickedDate) return
          const onCandleSeries = params.componentType === 'series' && params.seriesType === 'candlestick'
          const onXAxis = params.componentType === 'xAxis'
          if (!onCandleSeries && !onXAxis) return
          onCandleDoubleClick(clickedDate)
        },
      }
    : undefined

  return (
    <div style={{ width: '100%' }}>
      <ReactECharts option={option} style={{ width: '100%', height: 520 }} onEvents={onEvents} />
      <div
        style={{
          marginTop: 10,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
          padding: '8px 10px',
          borderRadius: 10,
          border: '1px solid rgba(31,49,48,0.12)',
          background: 'rgba(255,255,255,0.75)',
        }}
      >
        {primaryLegendItems.map((item) => (
          <span
            key={`legend-primary-${item.label}`}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '2px 8px',
              borderRadius: 999,
              border: '1px solid rgba(31,49,48,0.14)',
              color: '#2f5452',
              fontSize: 12,
              background: 'rgba(255,255,255,0.9)',
            }}
          >
            {renderLegendMarker(item.symbol, item.color)}
            <span>{item.label}</span>
          </span>
        ))}
        {annotationLegendItems.map((item) => (
          <span
            key={`legend-annotation-${item.label}`}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '2px 8px',
              borderRadius: 999,
              border: '1px solid rgba(31,49,48,0.14)',
              color: '#2f5452',
              fontSize: 12,
              background: 'rgba(248, 252, 250, 0.95)',
            }}
          >
            {renderLegendMarker(item.symbol, item.color)}
            <span>{item.label}</span>
          </span>
        ))}
      </div>
      <div
        style={{
          marginTop: 8,
          padding: '8px 10px',
          borderRadius: 10,
          border: '1px solid rgba(31,49,48,0.12)',
          background: 'rgba(255,255,255,0.62)',
          color: '#2f5452',
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          {'\u5a01\u79d1\u592b\u4e8b\u4ef6\u6807\u6ce8\u6e05\u5355'}
        </div>
        <div>{'\u5438\u7b79\u4e8b\u4ef6\uff1a'}{formatEventGuideWithZh(WYCKOFF_EVENT_GUIDE.accumulation)}</div>
        <div>{'\u6d3e\u53d1/\u98ce\u9669\u4e8b\u4ef6\uff1a'}{formatEventGuideWithZh(WYCKOFF_EVENT_GUIDE.risk)}</div>
        {unknownEventCodes.length > 0 ? (
          <div>{'\u672a\u5f52\u7c7b\u4e8b\u4ef6\u4ee3\u7801\uff1a'}{unknownEventCodes.join(' / ')}</div>
        ) : null}
        {unknownPhaseNames.length > 0 ? (
          <div>{'\u672a\u5f52\u7c7b\u9636\u6bb5\u540d\u79f0\uff1a'}{unknownPhaseNames.join(' / ')}</div>
        ) : null}
      </div>
    </div>
  )
}

