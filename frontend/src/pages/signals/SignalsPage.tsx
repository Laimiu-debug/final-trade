import { useQuery } from '@tanstack/react-query'
import { Card, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getSignals } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { SignalResult } from '@/types/contracts'

const signalColor: Record<string, string> = {
  B: 'red',
  A: 'green',
  C: 'orange',
}

const columns: ColumnsType<SignalResult> = [
  { title: '代码', dataIndex: 'symbol', width: 110 },
  { title: '名称', dataIndex: 'name', width: 120 },
  {
    title: '主信号',
    dataIndex: 'primary_signal',
    width: 90,
    render: (value: string) => <Tag color={signalColor[value] ?? 'default'}>{value}</Tag>,
  },
  {
    title: '次信号',
    dataIndex: 'secondary_signals',
    width: 130,
    render: (values: string[]) =>
      values.length === 0 ? '-' : values.map((value) => <Tag key={value}>{value}</Tag>),
  },
  { title: '触发日', dataIndex: 'trigger_date', width: 120 },
  { title: '失效日', dataIndex: 'expire_date', width: 120 },
  { title: '触发依据', dataIndex: 'trigger_reason' },
]

export function SignalsPage() {
  const signalQuery = useQuery({
    queryKey: ['signals'],
    queryFn: getSignals,
  })

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        title="待买信号"
        subtitle="冲突优先级固定 B > A > C，同日仅主信号进入主列表。"
        badge="规则化"
      />

      <Card className="glass-card" variant="borderless">
        <Table
          rowKey="symbol"
          loading={signalQuery.isLoading}
          dataSource={signalQuery.data?.items ?? []}
          columns={columns}
          pagination={false}
        />
      </Card>
    </Space>
  )
}


