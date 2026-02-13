import ReactECharts from 'echarts-for-react'
import type { CandlePoint, SignalResult, SignalType } from '@/types/contracts'
import { movingAverage } from '@/shared/utils/chart'

interface KLineChartProps {
  candles: CandlePoint[]
  signals?: SignalResult[]
  manualStartDate?: string
  aiBreakoutDate?: string
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

function resolveNearestTradingDateIndex(targetDate: string, tradingDates: string[]) {
  if (tradingDates.length === 0) return -1
  const exactIndex = tradingDates.indexOf(targetDate)
  if (exactIndex >= 0) return exactIndex

  const targetTs = Date.parse(targetDate)
  if (Number.isNaN(targetTs)) return -1

  for (let index = 0; index < tradingDates.length; index += 1) {
    const currentTs = Date.parse(tradingDates[index])
    if (Number.isNaN(currentTs)) continue
    if (currentTs >= targetTs) return index
  }

  return tradingDates.length - 1
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
  if (phase.startsWith('吸筹')) return 'rgba(22, 119, 255, 0.10)'
  if (phase.startsWith('派发')) return 'rgba(245, 34, 45, 0.10)'
  return 'rgba(120, 136, 153, 0.08)'
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

export function KLineChart({
  candles,
  signals = [],
  manualStartDate,
  aiBreakoutDate,
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

  for (const signal of signals) {
    const triggerIndex = resolveNearestTradingDateIndex(signal.trigger_date, xData)
    if (triggerIndex < 0) continue

    const mappedTriggerDate = xData[triggerIndex]
    const mappedHint = mappedTriggerDate === signal.trigger_date ? '' : ` -> ${mappedTriggerDate}`
    const phase = signal.wyckoff_phase?.trim() || '阶段未明'
    const event = signal.wyckoff_signal?.trim() || signal.wy_events?.[signal.wy_events.length - 1] || '无事件'

    const signalSequence: SignalType[] = [signal.primary_signal, ...signal.secondary_signals]
    const dedupedSequence = Array.from(new Set(signalSequence))
    dedupedSequence.forEach((signalType, sequenceIndex) => {
      const isPrimary = sequenceIndex === 0
      const markerName = isPrimary ? `${signalType}主信号` : `${signalType}次信号`
      markPointDrafts.push({
        dateKey: mappedTriggerDate,
        name: markerName,
        coord: [mappedTriggerDate, candles[triggerIndex].high],
        value: signalType,
        symbol: resolveSignalShape(signalType),
        symbolSize: isPrimary ? 16 : 12,
        tooltipText: `${markerName} | 阶段:${phase} | 事件:${event} | 触发:${signal.trigger_date}${mappedHint}`,
        itemStyle: {
          color: resolveSignalColor(signalType),
        },
      })
    })

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
          name: `阶段:${phase}`,
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

  const manualPoint = makeDateMarkPoint(manualStartDate, '人工启动日', 'low', '#13c2c2')
  if (manualPoint) {
    markPointDrafts.push(manualPoint)
  }
  const aiPoint = makeDateMarkPoint(aiBreakoutDate, 'AI起爆日', 'high', '#fa8c16')
  if (aiPoint) {
    markPointDrafts.push(aiPoint)
  }

  const allMarkPoints = toStackedMarkPoints(markPointDrafts)

  const markLineData = [
    manualStartDate && xData.includes(manualStartDate)
      ? {
          name: '人工启动日',
          xAxis: manualStartDate,
          lineStyle: { color: '#13c2c2', width: 1.4 },
          label: { formatter: '人工启动日' },
        }
      : null,
    aiBreakoutDate && xData.includes(aiBreakoutDate)
      ? {
          name: 'AI起爆日',
          xAxis: aiBreakoutDate,
          lineStyle: { color: '#fa8c16', width: 1.4 },
          label: { formatter: 'AI起爆日' },
        }
      : null,
  ].filter(Boolean)

  const option = {
    animation: true,
    legend: {
      top: 2,
      textStyle: {
        color: '#2f5452',
      },
      data: [
        '日K',
        'MA5',
        'MA10',
        'MA20',
        '成交量',
        'B信号(三角)',
        'A信号(菱形)',
        'C信号(圆形)',
        '人工启动日',
        'AI起爆日',
        '吸筹阶段区间',
        '派发阶段区间',
        '阶段未明区间',
      ],
    },
    tooltip: {
      trigger: 'axis',
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
        name: '日K',
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
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: '#8ca9a7',
        },
      },
      {
        name: 'B信号(三角)',
        type: 'scatter',
        data: [],
        symbol: 'triangle',
        symbolSize: 10,
        itemStyle: { color: '#eb8f34' },
      },
      {
        name: 'A信号(菱形)',
        type: 'scatter',
        data: [],
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color: '#1677ff' },
      },
      {
        name: 'C信号(圆形)',
        type: 'scatter',
        data: [],
        symbol: 'circle',
        symbolSize: 10,
        itemStyle: { color: '#7f8c8d' },
      },
      {
        name: '人工启动日',
        type: 'scatter',
        data: [],
        symbol: 'pin',
        symbolSize: 10,
        itemStyle: { color: '#13c2c2' },
      },
      {
        name: 'AI起爆日',
        type: 'scatter',
        data: [],
        symbol: 'pin',
        symbolSize: 10,
        itemStyle: { color: '#fa8c16' },
      },
      {
        name: '吸筹阶段区间',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(22, 119, 255, 0.50)' },
      },
      {
        name: '派发阶段区间',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(245, 34, 45, 0.50)' },
      },
      {
        name: '阶段未明区间',
        type: 'scatter',
        data: [],
        symbol: 'rect',
        symbolSize: 10,
        itemStyle: { color: 'rgba(120, 136, 153, 0.50)' },
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
