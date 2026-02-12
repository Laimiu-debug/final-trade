import ReactECharts from 'echarts-for-react'
import type { IntradayPoint } from '@/types/contracts'

interface IntradayChartProps {
  points: IntradayPoint[]
}

export function IntradayChart({ points }: IntradayChartProps) {
  const xData = points.map((item) => item.time)
  const priceData = points.map((item) => item.price)
  const avgPriceData = points.map((item) => item.avg_price)
  const volumeData = points.map((item) => item.volume)

  const option = {
    animation: true,
    legend: {
      top: 2,
      textStyle: { color: '#2f5452' },
      data: ['分时价', '均价', '成交量'],
    },
    tooltip: {
      trigger: 'axis',
    },
    axisPointer: {
      link: [{ xAxisIndex: [0, 1] }],
    },
    grid: [
      { left: '6%', right: '5%', top: '12%', height: '56%' },
      { left: '6%', right: '5%', top: '75%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: xData,
        boundaryGap: false,
      },
      {
        type: 'category',
        gridIndex: 1,
        data: xData,
        boundaryGap: false,
        axisLabel: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(31,49,48,0.14)' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { show: true, xAxisIndex: [0, 1], type: 'slider', top: '93%', start: 0, end: 100 },
    ],
    series: [
      {
        name: '分时价',
        type: 'line',
        data: priceData,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 1.7, color: '#0f8b6f' },
      },
      {
        name: '均价',
        type: 'line',
        data: avgPriceData,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 1.4, color: '#e88e1a' },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumeData,
        itemStyle: { color: '#8ca9a7' },
      },
    ],
  }

  return <ReactECharts option={option} style={{ width: '100%', height: 420 }} />
}

