import { useQuery } from '@tanstack/react-query'
import { App as AntdApp, Button, Card, Col, Row, Space, Statistic, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getReviewStats } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { TradeRecord } from '@/types/contracts'
import { formatPct } from '@/shared/utils/format'

const columns: ColumnsType<TradeRecord> = [
  { title: '代码', dataIndex: 'symbol', width: 110 },
  { title: '买入日', dataIndex: 'buy_date', width: 120 },
  { title: '买价', dataIndex: 'buy_price', width: 90 },
  { title: '卖出日', dataIndex: 'sell_date', width: 120 },
  { title: '卖价', dataIndex: 'sell_price', width: 90 },
  { title: '持仓天数', dataIndex: 'holding_days', width: 100 },
  { title: '盈亏金额', dataIndex: 'pnl_amount', width: 110 },
  {
    title: '盈亏比',
    dataIndex: 'pnl_ratio',
    width: 100,
    render: (value: number) => formatPct(value),
  },
]

export function ReviewPage() {
  const { message } = AntdApp.useApp()
  const reviewQuery = useQuery({
    queryKey: ['review'],
    queryFn: getReviewStats,
  })

  const stats = reviewQuery.data?.stats

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="交易记录与复盘" subtitle="原型阶段提供统计看板与导出入口（Mock响应）。" />

      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="胜率" value={stats?.win_rate ?? 0} formatter={(value) => formatPct(Number(value))} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card className="glass-card" variant="borderless">
            <Statistic
              title="总收益率"
              value={stats?.total_return ?? 0}
              formatter={(value) => formatPct(Number(value))}
            />
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
      </Row>

      <Card className="glass-card" variant="borderless">
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Space>
            <Button onClick={() => message.success('已触发 Excel 导出 (Mock)')}>导出 Excel</Button>
            <Button onClick={() => message.success('已触发 PDF 导出 (Mock)')}>导出 PDF</Button>
          </Space>
          <Table
            rowKey={(row) => `${row.symbol}-${row.buy_date}`}
            columns={columns}
            dataSource={reviewQuery.data?.trades ?? []}
            loading={reviewQuery.isLoading}
            pagination={false}
            scroll={{ x: 900 }}
          />
        </Space>
      </Card>
    </Space>
  )
}

