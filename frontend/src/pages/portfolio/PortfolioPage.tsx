import { useQuery } from '@tanstack/react-query'
import { Card, Col, Row, Space, Statistic, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getPortfolio } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { PortfolioPosition } from '@/types/contracts'
import { formatMoney, formatPct } from '@/shared/utils/format'

const columns: ColumnsType<PortfolioPosition> = [
  { title: '代码', dataIndex: 'symbol', width: 110 },
  { title: '名称', dataIndex: 'name', width: 120 },
  { title: '数量', dataIndex: 'quantity', width: 100 },
  { title: '成本', dataIndex: 'avg_cost', width: 100 },
  { title: '现价', dataIndex: 'current_price', width: 100 },
  {
    title: '盈亏比',
    dataIndex: 'pnl_ratio',
    width: 100,
    render: (value: number) => formatPct(value),
  },
  { title: '持仓天数', dataIndex: 'holding_days', width: 110 },
]

export function PortfolioPage() {
  const portfolioQuery = useQuery({
    queryKey: ['portfolio'],
    queryFn: getPortfolio,
  })

  const data = portfolioQuery.data

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="持仓管理" subtitle="展示模拟持仓、仓位盈亏与资金分布。" />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="总资产" value={data?.total_asset ?? 0} formatter={(val) => formatMoney(Number(val))} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="可用现金" value={data?.cash ?? 0} formatter={(val) => formatMoney(Number(val))} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card className="glass-card" variant="borderless">
            <Statistic
              title="持仓市值"
              value={data?.position_value ?? 0}
              formatter={(val) => formatMoney(Number(val))}
            />
          </Card>
        </Col>
      </Row>
      <Card className="glass-card" variant="borderless">
        <Table
          rowKey="symbol"
          columns={columns}
          dataSource={data?.positions ?? []}
          loading={portfolioQuery.isLoading}
          pagination={false}
        />
      </Card>
    </Space>
  )
}


