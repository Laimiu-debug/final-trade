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

function resolvePhaseAreaColor(phase: string) {
  if (phase.includes('\u5438\u7b79') || phase.toLowerCase().includes('accum')) return 'rgba(22, 119, 255, 0.10)'
  if (phase.includes('\u6d3e\u53d1') || phase.toLowerCase().includes('distrib')) return 'rgba(245, 34, 45, 0.10)'
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
  const stageRangeSet = new Set<string>()
  const stageRangeData: StageRangeItem[] = []
  const signalSummaryByDate = new Map<string, string[]>()

  for (const signal of signals) {
    const triggerIndex = resolveNearestTradingDateIndex(signal.trigger_date, xData)
    if (triggerIndex < 0) continue

    const mappedTriggerDate = xData[triggerIndex]
    const mappedHint = mappedTriggerDate === signal.trigger_date ? '' : ` -> ${mappedTriggerDate}`
    const phase = signal.wyckoff_phase?.trim() || '\u9636\u6bb5\u672a\u660e'
    const event = signal.wyckoff_signal?.trim() || signal.wy_events?.[signal.wy_events.length - 1] || '\u65e0\u4e8b\u4ef6'

    const signalSequence: SignalType[] = [signal.primary_signal, ...signal.secondary_signals]
    const dedupedSequence = Array.from(new Set(signalSequence))
    dedupedSequence.forEach((signalType, sequenceIndex) => {
      const isPrimary = sequenceIndex === 0
      const markerName = isPrimary ? `${signalType}\u4e3b\u4fe1\u53f7` : `${signalType}\u6b21\u4fe1\u53f7`
      markPointDrafts.push({
        dateKey: mappedTriggerDate,
        name: markerName,
        coord: [mappedTriggerDate, candles[triggerIndex].high],
        value: signalType,
        symbol: resolveSignalShape(signalType),
        symbolSize: isPrimary ? 16 : 12,
        tooltipText: `${markerName} | \u9636\u6bb5:${phase} | \u4e8b\u4ef6:${event} | \u89e6\u53d1:${signal.trigger_date}${mappedHint}`,
        itemStyle: {
          color: resolveSignalColor(signalType),
        },
      })
    })

    const summaryLine = `${dedupedSequence.join('/')} | ${phase} | ${event}`
    const existedSummary = signalSummaryByDate.get(mappedTriggerDate)
    if (existedSummary) {
      existedSummary.push(summaryLine)
    } else {
      signalSummaryByDate.set(mappedTriggerDate, [summaryLine])
    }

    const expireSource = signal.expire_date || signal.trigger_date
    const expireIndexRaw = resolveNearestTradingDateIndex(expireSource, xData)
    if (expireIndexRaw < 0) continue

    const minSpanBars = Math.max(3, Math.min(8, (signal.wy_event_count ?? 1) + 2))
    const minSpanEnd = Math.min(xData.length - 1, triggerIndex + minSpanBars - 1)
    let expireIndex = Math.max(expireIndexRaw, minSpanEnd)
    if (expireIndex < triggerIndex) {
      expireIndex = triggerIndex
    }

    const rangeStart = xData[triggerIndex]
    const rangeEnd = xData[expireIndex]
    const rangeKey = `${phase}|${rangeStart}|${rangeEnd}`
    if (!stageRangeSet.has(rangeKey)) {
      stageRangeSet.add(rangeKey)
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

  const markLineData = [
    resolveDateMarkLine(manualStartDate, xData, '\u4eba\u5de5\u542f\u52a8\u65e5', '#13c2c2'),
    resolveDateMarkLine(aiBreakoutDate, xData, 'AI\u8d77\u7206\u65e5', '#fa8c16'),
  ].filter(Boolean)

  const option = {
    animation: true,
    legend: {
      top: 2,
      textStyle: {
        color: '#2f5452',
      },
      data: [
        '\u65e5K',
        'MA5',
        'MA10',
        'MA20',
        '\u6210\u4ea4\u91cf',
        'B\u4fe1\u53f7(\u4e09\u89d2)',
        'A\u4fe1\u53f7(\u83f1\u5f62)',
        'C\u4fe1\u53f7(\u5706\u5f62)',
        '\u4eba\u5de5\u542f\u52a8\u65e5',
        'AI\u8d77\u7206\u65e5',
        '\u5438\u7b79\u9636\u6bb5\u533a\u95f4',
        '\u6d3e\u53d1\u9636\u6bb5\u533a\u95f4',
        '\u9636\u6bb5\u672a\u660e\u533a\u95f4',
        '\u7edf\u8ba1\u533a\u95f4',
      ],
    },
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
      { left: '6%', right: '5%', top: '10%', height: '58%' },
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
        name: 'B\u4fe1\u53f7(\u4e09\u89d2)',
        type: 'scatter',
        data: [],
        symbol: 'triangle',
        symbolSize: 10,
        itemStyle: { color: '#eb8f34' },
      },
      {
        name: 'A\u4fe1\u53f7(\u83f1\u5f62)',
        type: 'scatter',
        data: [],
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color: '#1677ff' },
      },
      {
        name: 'C\u4fe1\u53f7(\u5706\u5f62)',
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
        name: '\u5438\u7b79\u9636\u6bb5\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(22, 119, 255, 0.50)' },
      },
      {
        name: '\u6d3e\u53d1\u9636\u6bb5\u533a\u95f4',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(245, 34, 45, 0.50)' },
      },
      {
        name: '\u9636\u6bb5\u672a\u660e\u533a\u95f4',
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

  return <ReactECharts option={option} style={{ width: '100%', height: 520 }} onEvents={onEvents} />
}
