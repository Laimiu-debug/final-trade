import { useMemo, useRef, useState } from 'react'
import dayjs, { Dayjs } from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  DatePicker,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import ReactECharts from 'echarts-for-react'
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import * as XLSX from 'xlsx'
import { ApiError } from '@/shared/api/client'
import { getReviewStats } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { ReviewResponse, TradeRecord } from '@/types/contracts'
import { formatMoney, formatPct } from '@/shared/utils/format'

function formatApiError(error: unknown) {
  if (error instanceof ApiError) {
    return error.message || `请求失败：${error.code}`
  }
  if (error instanceof Error) {
    return error.message || '请求失败'
  }
  return '请求失败'
}

function bufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer)
  const chunkSize = 0x8000
  let binary = ''
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

const tradeColumns: ColumnsType<TradeRecord> = [
  { title: '代码', dataIndex: 'symbol', width: 110 },
  { title: '买入日', dataIndex: 'buy_date', width: 120 },
  { title: '买价', dataIndex: 'buy_price', width: 100 },
  { title: '卖出日', dataIndex: 'sell_date', width: 120 },
  { title: '卖价', dataIndex: 'sell_price', width: 100 },
  { title: '数量', dataIndex: 'quantity', width: 90 },
  { title: '持仓天数', dataIndex: 'holding_days', width: 110 },
  {
    title: '盈亏金额',
    dataIndex: 'pnl_amount',
    width: 130,
    render: (value: number) => <span style={{ color: value >= 0 ? '#19744f' : '#c4473d' }}>{formatMoney(value)}</span>,
  },
  {
    title: '盈亏比',
    dataIndex: 'pnl_ratio',
    width: 100,
    render: (value: number) => formatPct(value),
  },
]

function isSameDateRange(prev: [Dayjs, Dayjs], next: [Dayjs, Dayjs]) {
  return prev[0].isSame(next[0], 'day') && prev[1].isSame(next[1], 'day')
}

export function ReviewPage() {
  const { message } = AntdApp.useApp()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(90, 'day'), dayjs()])
  const [dateAxis, setDateAxis] = useState<'sell' | 'buy'>('sell')
  const equityChartRef = useRef<ReactECharts | null>(null)
  const drawdownChartRef = useRef<ReactECharts | null>(null)
  const monthlyChartRef = useRef<ReactECharts | null>(null)

  const reviewQuery = useQuery({
    queryKey: ['review', range[0].format('YYYY-MM-DD'), range[1].format('YYYY-MM-DD'), dateAxis],
    queryFn: () =>
      getReviewStats({
        date_from: range[0].format('YYYY-MM-DD'),
        date_to: range[1].format('YYYY-MM-DD'),
        date_axis: dateAxis,
      }),
  })

  const review = reviewQuery.data
  const stats = review?.stats

  const equityOption = useMemo(() => {
    const curve = review?.equity_curve ?? []
    return {
      animationDuration: 300,
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: curve.map((row) => row.date) },
      yAxis: { type: 'value', scale: true },
      series: [
        {
          name: '权益',
          type: 'line',
          smooth: true,
          data: curve.map((row) => row.equity),
          lineStyle: { width: 2, color: '#0f8b6f' },
          areaStyle: { color: 'rgba(15,139,111,0.16)' },
        },
      ],
      grid: { left: 48, right: 20, top: 24, bottom: 36 },
    }
  }, [review?.equity_curve])

  const drawdownOption = useMemo(() => {
    const curve = review?.drawdown_curve ?? []
    return {
      animationDuration: 300,
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: curve.map((row) => row.date) },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => `${(value * 100).toFixed(1)}%`,
        },
      },
      series: [
        {
          name: '回撤',
          type: 'line',
          smooth: true,
          data: curve.map((row) => row.drawdown),
          lineStyle: { width: 2, color: '#c4473d' },
          areaStyle: { color: 'rgba(196,71,61,0.16)' },
        },
      ],
      grid: { left: 48, right: 20, top: 24, bottom: 36 },
    }
  }, [review?.drawdown_curve])

  const monthlyOption = useMemo(() => {
    const rows = review?.monthly_returns ?? []
    return {
      animationDuration: 300,
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: rows.map((row) => row.month) },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => `${(value * 100).toFixed(1)}%`,
        },
      },
      series: [
        {
          name: '月收益',
          type: 'bar',
          data: rows.map((row) => row.return_ratio),
          itemStyle: {
            color: (params: { data: number }) => (params.data >= 0 ? '#19744f' : '#c4473d'),
          },
        },
      ],
      grid: { left: 48, right: 20, top: 24, bottom: 36 },
    }
  }, [review?.monthly_returns])

  async function handleExportExcel() {
    try {
      const payload = review as ReviewResponse | undefined
      if (!payload) {
        message.warning('暂无可导出数据')
        return
      }

      const wb = XLSX.utils.book_new()
      const overview = [
        {
          date_from: payload.range.date_from,
          date_to: payload.range.date_to,
          win_rate: payload.stats.win_rate,
          total_return: payload.stats.total_return,
          max_drawdown: payload.stats.max_drawdown,
          avg_pnl_ratio: payload.stats.avg_pnl_ratio,
          trade_count: payload.stats.trade_count,
          win_count: payload.stats.win_count,
          loss_count: payload.stats.loss_count,
          profit_factor: payload.stats.profit_factor,
        },
      ]
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(overview), 'Overview')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(payload.trades), 'Trades')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(payload.monthly_returns), 'Monthly')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(payload.equity_curve), 'Equity')
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet([payload.cost_snapshot]), 'Config')
      XLSX.writeFile(wb, `review-${dayjs().format('YYYYMMDD-HHmmss')}.xlsx`)
      message.success('Excel 导出完成')
    } catch (error) {
      message.error(formatApiError(error))
    }
  }

  async function handleExportCSV() {
    try {
      const trades = review?.trades ?? []
      if (trades.length === 0) {
        message.warning('暂无可导出交易明细')
        return
      }
      const headers = ['symbol', 'buy_date', 'buy_price', 'sell_date', 'sell_price', 'quantity', 'holding_days', 'pnl_amount', 'pnl_ratio']
      const lines = [headers.join(',')]
      trades.forEach((trade) => {
        lines.push(
          [
            trade.symbol,
            trade.buy_date,
            trade.buy_price,
            trade.sell_date,
            trade.sell_price,
            trade.quantity,
            trade.holding_days,
            trade.pnl_amount,
            trade.pnl_ratio,
          ].join(','),
        )
      })
      const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8;' })
      downloadBlob(`trades-${dayjs().format('YYYYMMDD-HHmmss')}.csv`, blob)
      message.success('CSV 导出完成')
    } catch (error) {
      message.error(formatApiError(error))
    }
  }

  async function handleExportPDF() {
    try {
      const payload = review as ReviewResponse | undefined
      if (!payload) {
        message.warning('暂无可导出数据')
        return
      }

      const doc = new jsPDF({ unit: 'pt', format: 'a4' })
      let useCnFont = false
      try {
        const fontResp = await fetch('/fonts/LXGWWenKai-Regular.ttf')
        if (fontResp.ok) {
          const buffer = await fontResp.arrayBuffer()
          const base64 = bufferToBase64(buffer)
          doc.addFileToVFS('LXGWWenKai-Regular.ttf', base64)
          doc.addFont('LXGWWenKai-Regular.ttf', 'LXGWWenKai', 'normal')
          doc.setFont('LXGWWenKai', 'normal')
          useCnFont = true
        }
      } catch {
        useCnFont = false
      }

      const safeText = (text: string) => {
        if (useCnFont) return text
        return Array.from(text)
          .filter((char) => {
            const code = char.charCodeAt(0)
            return code >= 32 && code <= 126
          })
          .join('')
      }
      let cursorY = 40

      doc.setFontSize(16)
      doc.text(safeText('模拟交易复盘报告'), 40, cursorY)
      cursorY += 20
      doc.setFontSize(10)
      doc.text(
        safeText(`区间: ${payload.range.date_from} ~ ${payload.range.date_to} (axis=${payload.range.date_axis})`),
        40,
        cursorY,
      )
      cursorY += 18

      const statRows = [
        ['胜率', formatPct(payload.stats.win_rate)],
        ['总收益率', formatPct(payload.stats.total_return)],
        ['最大回撤', formatPct(payload.stats.max_drawdown)],
        ['平均盈亏比', formatPct(payload.stats.avg_pnl_ratio)],
        ['交易笔数', String(payload.stats.trade_count)],
        ['盈利笔数', String(payload.stats.win_count)],
        ['亏损笔数', String(payload.stats.loss_count)],
        ['Profit Factor', String(payload.stats.profit_factor.toFixed(3))],
      ]
      autoTable(doc, {
        startY: cursorY,
        styles: { font: useCnFont ? 'LXGWWenKai' : 'helvetica', fontSize: 9 },
        head: [[safeText('指标'), safeText('数值')]],
        body: statRows.map((row) => [safeText(row[0]), row[1]]),
        margin: { left: 40, right: 40 },
      })
      cursorY = ((doc as unknown as { lastAutoTable?: { finalY?: number } }).lastAutoTable?.finalY ?? cursorY) + 18

      const addChart = (title: string, ref: React.RefObject<ReactECharts | null>) => {
        const instance = ref.current?.getEchartsInstance()
        if (!instance) return
        const img = instance.getDataURL({
          pixelRatio: 2,
          backgroundColor: '#ffffff',
          type: 'png',
        })
        if (cursorY > 680) {
          doc.addPage()
          cursorY = 40
        }
        doc.setFontSize(11)
        doc.text(safeText(title), 40, cursorY)
        cursorY += 8
        doc.addImage(img, 'PNG', 40, cursorY, 515, 150)
        cursorY += 168
      }

      addChart('权益曲线', equityChartRef)
      addChart('回撤曲线', drawdownChartRef)
      addChart('月度收益', monthlyChartRef)

      if (cursorY > 580) {
        doc.addPage()
        cursorY = 40
      }
      autoTable(doc, {
        startY: cursorY,
        styles: { font: useCnFont ? 'LXGWWenKai' : 'helvetica', fontSize: 8 },
        head: [[safeText('Top Trades'), safeText('Symbol'), safeText('PnL')]],
        body: (payload.top_trades || []).map((row, index) => [
          String(index + 1),
          row.symbol,
          String(row.pnl_amount),
        ]),
        margin: { left: 40, right: 40 },
      })
      cursorY = ((doc as unknown as { lastAutoTable?: { finalY?: number } }).lastAutoTable?.finalY ?? cursorY) + 12

      autoTable(doc, {
        startY: cursorY,
        styles: { font: useCnFont ? 'LXGWWenKai' : 'helvetica', fontSize: 8 },
        head: [[safeText('Bottom Trades'), safeText('Symbol'), safeText('PnL')]],
        body: (payload.bottom_trades || []).map((row, index) => [
          String(index + 1),
          row.symbol,
          String(row.pnl_amount),
        ]),
        margin: { left: 40, right: 40 },
      })
      cursorY = ((doc as unknown as { lastAutoTable?: { finalY?: number } }).lastAutoTable?.finalY ?? cursorY) + 12

      if (cursorY > 500) {
        doc.addPage()
        cursorY = 40
      }
      autoTable(doc, {
        startY: cursorY,
        styles: { font: useCnFont ? 'LXGWWenKai' : 'helvetica', fontSize: 7 },
        head: [[safeText('交易明细'), safeText('买入日'), safeText('卖出日'), safeText('数量'), safeText('盈亏额')]],
        body: payload.trades.map((row) => [
          row.symbol,
          row.buy_date,
          row.sell_date,
          String(row.quantity),
          String(row.pnl_amount),
        ]),
        margin: { left: 40, right: 40 },
      })

      doc.save(`review-${dayjs().format('YYYYMMDD-HHmmss')}.pdf`)
      message.success('PDF 导出完成')
    } catch (error) {
      message.error(formatApiError(error))
    }
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="交易记录与复盘" subtitle="默认近90天，支持区间筛选、三类图表和 Excel/CSV/PDF 导出。" />

      <Card className="glass-card" variant="borderless">
        <Space wrap>
          <DatePicker.RangePicker
            value={range}
            onChange={(value) => {
              if (!value || !value[0] || !value[1]) return
              const nextRange: [Dayjs, Dayjs] = [value[0], value[1]]
              setRange((prev) => (isSameDateRange(prev, nextRange) ? prev : nextRange))
            }}
          />
          <Radio.Group
            value={dateAxis}
            optionType="button"
            options={[
              { label: '按卖出日', value: 'sell' },
              { label: '按买入日', value: 'buy' },
            ]}
            onChange={(event) => setDateAxis(event.target.value as 'sell' | 'buy')}
          />
          <Button onClick={handleExportExcel}>导出 Excel</Button>
          <Button onClick={handleExportCSV}>导出 CSV</Button>
          <Button onClick={handleExportPDF}>导出 PDF</Button>
          <Typography.Text type="secondary">
            成本参数快照：佣金 {review?.cost_snapshot?.commission_rate ?? 0} / 印花税{' '}
            {review?.cost_snapshot?.stamp_tax_rate ?? 0}
          </Typography.Text>
        </Space>
      </Card>

      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="胜率" value={stats?.win_rate ?? 0} formatter={(value) => formatPct(Number(value))} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="总收益率" value={stats?.total_return ?? 0} formatter={(value) => formatPct(Number(value))} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic
              title="最大回撤"
              value={stats?.max_drawdown ?? 0}
              formatter={(value) => formatPct(Number(value))}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic
              title="平均盈亏比"
              value={stats?.avg_pnl_ratio ?? 0}
              formatter={(value) => formatPct(Number(value))}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="交易笔数" value={stats?.trade_count ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="盈利笔数" value={stats?.win_count ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="亏损笔数" value={stats?.loss_count ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="Profit Factor" value={stats?.profit_factor ?? 0} precision={3} />
          </Card>
        </Col>
      </Row>

      <Card className="glass-card" variant="borderless" title="权益曲线">
        <ReactECharts ref={equityChartRef} option={equityOption} style={{ height: 300 }} notMerge />
      </Card>

      <Card className="glass-card" variant="borderless" title="回撤曲线">
        <ReactECharts ref={drawdownChartRef} option={drawdownOption} style={{ height: 300 }} notMerge />
      </Card>

      <Card className="glass-card" variant="borderless" title="月度收益">
        <ReactECharts ref={monthlyChartRef} option={monthlyOption} style={{ height: 300 }} notMerge />
      </Card>

      <Card className="glass-card" variant="borderless" title="Top / Bottom 交易">
        <Row gutter={12}>
          <Col xs={24} md={12}>
            <Typography.Title level={5}>Top 交易</Typography.Title>
            <Table
              rowKey={(row) => `top-${row.symbol}-${row.sell_date}-${row.buy_date}`}
              columns={tradeColumns}
              dataSource={review?.top_trades ?? []}
              loading={reviewQuery.isLoading}
              pagination={false}
              size="small"
              scroll={{ x: 850 }}
            />
          </Col>
          <Col xs={24} md={12}>
            <Typography.Title level={5}>Bottom 交易</Typography.Title>
            <Table
              rowKey={(row) => `bottom-${row.symbol}-${row.sell_date}-${row.buy_date}`}
              columns={tradeColumns}
              dataSource={review?.bottom_trades ?? []}
              loading={reviewQuery.isLoading}
              pagination={false}
              size="small"
              scroll={{ x: 850 }}
            />
          </Col>
        </Row>
      </Card>

      <Card className="glass-card" variant="borderless" title="交易明细">
        <Table
          rowKey={(row) => `${row.symbol}-${row.buy_date}-${row.sell_date}-${row.quantity}`}
          columns={tradeColumns}
          dataSource={review?.trades ?? []}
          loading={reviewQuery.isLoading}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 1000 }}
        />
      </Card>

      {reviewQuery.error ? (
        <Card className="glass-card" variant="borderless">
          <Typography.Text type="danger">{formatApiError(reviewQuery.error)}</Typography.Text>
        </Card>
      ) : null}
    </Space>
  )
}
