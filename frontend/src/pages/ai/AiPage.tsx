import { useQuery } from '@tanstack/react-query'
import { Card, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getAIRecords } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { AIAnalysisRecord } from '@/types/contracts'

const columns: ColumnsType<AIAnalysisRecord> = [
  { title: '股票', dataIndex: 'symbol', width: 110 },
  { title: 'Provider', dataIndex: 'provider', width: 100 },
  { title: '抓取时间', dataIndex: 'fetched_at', width: 170 },
  {
    title: '结论',
    dataIndex: 'conclusion',
    width: 100,
    render: (value: string) => <Tag color={value === '发酵中' ? 'green' : value === '高潮' ? 'orange' : 'default'}>{value}</Tag>,
  },
  { title: '置信度', dataIndex: 'confidence', width: 90 },
  { title: '摘要', dataIndex: 'summary' },
]

export function AiPage() {
  const query = useQuery({
    queryKey: ['ai-records'],
    queryFn: getAIRecords,
  })

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="AI题材分析" subtitle="支持多 provider，当前页面展示分析历史与来源追踪。" />
      <Card className="glass-card" variant="borderless">
        <Table
          rowKey={(row) => `${row.symbol}-${row.fetched_at}`}
          loading={query.isLoading}
          dataSource={query.data?.items ?? []}
          columns={columns}
          expandable={{
            expandedRowRender: (record) => (
              <div>
                来源:
                {record.source_urls.map((url) => (
                  <div key={url}>{url}</div>
                ))}
              </div>
            ),
          }}
          pagination={{ pageSize: 6 }}
        />
      </Card>
    </Space>
  )
}


