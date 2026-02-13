import ReactECharts from 'echarts-for-react'
import type { CandlePoint, SignalResult } from '@/types/contracts'
import { movingAverage } from '@/shared/utils/chart'

interface KLineChartProps {
  candles: CandlePoint[]
  signals?: SignalResult[]
  manualStartDate?: string
  aiBreakoutDate?: string
  onCandleDoubleClick?: (date: string) => void
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

  const signalMarkPoints = signals
    .map((signal) => {
      const index = xData.indexOf(signal.trigger_date)
      if (index < 0) return null
      return {
        name: `${signal.primary_signal}买点`,
        coord: [signal.trigger_date, candles[index].close],
        value: signal.primary_signal,
        itemStyle: {
          color: signal.primary_signal === 'B' ? '#eb8f34' : signal.primary_signal === 'A' ? '#1677ff' : '#7f8c8d',
        },
      }
    })
    .filter(Boolean)

  function makeDateMarkPoint(date: string | undefined, label: string, type: 'high' | 'low', color: string) {
    if (!date) return null
    const index = xData.indexOf(date)
    if (index < 0) return null
    return {
      name: label,
      coord: [date, type === 'high' ? candles[index].high : candles[index].low],
      value: label,
      itemStyle: { color },
      label: {
        color: '#fff',
      },
    }
  }

  const overlayMarkPoints = [
    makeDateMarkPoint(manualStartDate, '人工启动日', 'low', '#13c2c2'),
    makeDateMarkPoint(aiBreakoutDate, 'AI起爆日', 'high', '#fa8c16'),
  ].filter(Boolean)

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
      data: ['日K', 'MA5', 'MA10', 'MA20', '成交量'],
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
          symbolSize: 46,
          label: { color: '#fff', fontWeight: 700 },
          data: [...signalMarkPoints, ...overlayMarkPoints],
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
