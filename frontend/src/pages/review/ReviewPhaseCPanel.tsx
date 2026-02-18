import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Input, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getMarketNews } from '@/shared/api/endpoints'
import type { MarketNewsItem } from '@/types/contracts'

type ReviewPhaseCPanelProps = {
  dateFrom: string
  dateTo: string
}

function compactText(value: string, limit = 120) {
  const text = value.trim()
  if (!text) return '-'
  if (text.length <= limit) return text
  return `${text.slice(0, limit - 1)}…`
}

export function ReviewPhaseCPanel({ dateFrom, dateTo }: ReviewPhaseCPanelProps) {
  const [draftQuery, setDraftQuery] = useState('A股 热点')
  const [query, setQuery] = useState('A股 热点')

  const newsQuery = useQuery({
    queryKey: ['market-news', query],
    queryFn: () => getMarketNews({ query, limit: 24 }),
  })

  const columns: ColumnsType<MarketNewsItem> = useMemo(
    () => [
      {
        title: '时间',
        dataIndex: 'pub_date',
        width: 200,
        render: (value: string) => compactText(value, 22),
      },
      {
        title: '来源',
        dataIndex: 'source_name',
        width: 140,
        render: (value: string) => <Tag>{value || '-'}</Tag>,
      },
      {
        title: '标题',
        dataIndex: 'title',
        render: (value: string, row) => (
          <a href={row.url} target="_blank" rel="noreferrer">
            {compactText(value, 80)}
          </a>
        ),
      },
      {
        title: '摘要',
        dataIndex: 'snippet',
        render: (value: string) => compactText(value, 120),
      },
    ],
    [],
  )

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Typography.Text strong>Phase C: 资讯面板（起步版）</Typography.Text>
          <Typography.Text type="secondary">
            当前复盘区间 {dateFrom} ~ {dateTo}。该面板通过后端代理抓取资讯，不直接由前端跨域请求。
          </Typography.Text>
          <Space wrap>
            <Input
              style={{ width: 320 }}
              allowClear
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="输入关键词，例如：半导体 / 机器人 / A股"
              onPressEnter={() => setQuery(draftQuery.trim() || 'A股 热点')}
            />
            <Button type="primary" onClick={() => setQuery(draftQuery.trim() || 'A股 热点')}>
              搜索资讯
            </Button>
            <Button onClick={() => void newsQuery.refetch()} loading={newsQuery.isFetching}>
              刷新
            </Button>
          </Space>
        </Space>
      </Card>

      {newsQuery.data?.degraded ? (
        <Alert
          showIcon
          type="warning"
          message="资讯已降级"
          description={newsQuery.data.degraded_reason || '当前资讯源可用性较低，已返回可用结果。'}
        />
      ) : null}

      <Card size="small" title={`资讯列表（${newsQuery.data?.items.length ?? 0} 条）`}>
        <Table
          rowKey={(row) => `${row.url}-${row.pub_date}`}
          columns={columns}
          dataSource={newsQuery.data?.items ?? []}
          loading={newsQuery.isLoading}
          size="small"
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 1100 }}
        />
      </Card>
    </Space>
  )
}
