import ReactECharts from 'echarts-for-react'
import type { SignalResult, CandlePoint } from '@/types/contracts'
import { movingAverage } from '@/shared/utils/chart'

interface KLineChartProps {
  candles: CandlePoint[]
  signals?: SignalResult[]
  onCandleDoubleClick?: (date: string) => void
}

export function KLineChart({ candles, signals = [], onCandleDoubleClick }: KLineChartProps) {
  const xData = candles.map((item) => item.time)
  const candleData = candles.map((item) => [item.open, item.close, item.low, item.high])
  const volumes = candles.map((item) => item.volume)
  const ma5 = movingAverage(candles, 5)
  const ma10 = movingAverage(candles, 10)
  const ma20 = movingAverage(candles, 20)

  const markPoints = signals
    .map((signal) => {
      const index = xData.indexOf(signal.trigger_date)
      if (index < 0) return null
      return {
        name: `${signal.primary_signal}买点`,
        coord: [signal.trigger_date, candles[index].close],
        value: signal.primary_signal,
      }
    })
    .filter(Boolean)

  const option = {
    animation: true,
    legend: {
      top: 2,
      textStyle: {
        color: '#2f5452',
      },
      data: ['K线', 'MA5', 'MA10', 'MA20', '成交量'],
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
        name: 'K线',
        type: 'candlestick',
        data: candleData,
        itemStyle: {
          color: '#ce5649',
          color0: '#1a8b66',
          borderColor: '#ce5649',
          borderColor0: '#1a8b66',
        },
        markPoint: {
          symbolSize: 44,
          label: { color: '#fff', fontWeight: 700 },
          data: markPoints,
        },
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#e88e1a' } },
      { name: 'MA10', type: 'line', data: ma10, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#0f8b6f' } },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#3160db' } },
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
          const onCandleSeries =
            params.componentType === 'series' && params.seriesType === 'candlestick'
          const onXAxis = params.componentType === 'xAxis'
          if (!onCandleSeries && !onXAxis) return
          onCandleDoubleClick(clickedDate)
        },
      }
    : undefined

  return <ReactECharts option={option} style={{ width: '100%', height: 520 }} onEvents={onEvents} />
}
