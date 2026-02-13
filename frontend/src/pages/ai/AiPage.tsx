import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App as AntdApp, Button, Card, Input, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { deleteAIRecord, getAIRecords } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import { useUIStore } from '@/state/uiStore'
import type { AIAnalysisRecord } from '@/types/contracts'

export function AiPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const syncLatestAIRecords = useUIStore((state) => state.syncLatestAIRecords)
  const [keyword, setKeyword] = useState('')
  const [providerFilters, setProviderFilters] = useState<string[]>([])
  const [conclusionFilters, setConclusionFilters] = useState<string[]>([])

  const query = useQuery({
    queryKey: ['ai-records'],
    queryFn: getAIRecords,
  })

  useEffect(() => {
    if (!query.data?.items) return
    syncLatestAIRecords(query.data.items)
  }, [query.data?.items, syncLatestAIRecords])

  const items = query.data?.items ?? []

  const providerOptions = useMemo(
    () =>
      Array.from(new Set(items.map((item) => item.provider)))
        .sort((a, b) => a.localeCompare(b))
        .map((value) => ({ label: value, value })),
    [items],
  )

  const conclusionOptions = useMemo(
    () =>
      Array.from(new Set(items.map((item) => item.conclusion)))
        .sort((a, b) => a.localeCompare(b))
        .map((value) => ({ label: value, value })),
    [items],
  )

  const filteredItems = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()
    return items.filter((item) => {
      const stockName = item.name ?? ''
      const matchesKeyword =
        normalizedKeyword.length === 0
        || stockName.toLowerCase().includes(normalizedKeyword)
        || item.symbol.toLowerCase().includes(normalizedKeyword)
      if (!matchesKeyword) return false
      if (providerFilters.length > 0 && !providerFilters.includes(item.provider)) return false
      if (conclusionFilters.length > 0 && !conclusionFilters.includes(item.conclusion)) return false
      return true
    })
  }, [conclusionFilters, items, keyword, providerFilters])

  const deleteMutation = useMutation({
    mutationFn: (record: AIAnalysisRecord) =>
      deleteAIRecord(record.symbol, record.fetched_at, record.provider),
    onSuccess: (result) => {
      if (result.deleted) {
        message.success('已删除 AI 分析记录')
      } else {
        message.info('未找到对应记录，可能已被删除')
      }
      void queryClient.invalidateQueries({ queryKey: ['ai-records'] })
    },
    onError: () => {
      message.error('删除失败，请稍后重试')
    },
  })

  const columns: ColumnsType<AIAnalysisRecord> = [
    {
      title: '股票',
      key: 'stock',
      width: 140,
      render: (_, record) => <Typography.Text strong>{record.name || record.symbol.toUpperCase()}</Typography.Text>,
    },
    { title: 'Provider', dataIndex: 'provider', width: 100 },
    { title: '抓取时间', dataIndex: 'fetched_at', width: 170 },
    {
      title: '结论',
      dataIndex: 'conclusion',
      width: 100,
      render: (value: string) => (
        <Tag color={value === '发酵中' ? 'green' : value === '高潮' ? 'orange' : 'default'}>{value}</Tag>
      ),
    },
    {
      title: '起爆日期',
      dataIndex: 'breakout_date',
      width: 120,
      render: (value: string | undefined) => value || '--',
    },
    {
      title: '趋势牛类型',
      dataIndex: 'trend_bull_type',
      width: 140,
      render: (value: string | undefined) => value || '--',
    },
    {
      title: '题材',
      dataIndex: 'theme_name',
      width: 120,
      render: (value: string | undefined) => value || '--',
    },
    { title: '置信度', dataIndex: 'confidence', width: 90 },
    { title: '摘要', dataIndex: 'summary' },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/stocks/${record.symbol}/chart`)}>
            去K线标注
          </Button>
          <Popconfirm
            title="删除这条 AI 分析记录?"
            okText="删除"
            cancelText="取消"
            onConfirm={() => {
              void deleteMutation.mutateAsync(record)
            }}
          >
            <Button size="small" danger loading={deleteMutation.isPending}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="AI题材分析" subtitle="支持删除历史记录，并与个股K线标注页联动。" />
      <Card className="glass-card" variant="borderless">
        <Space wrap style={{ width: '100%', marginBottom: 12, justifyContent: 'space-between' }}>
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="搜索股票名/代码"
              value={keyword}
              onChange={(evt) => setKeyword(evt.target.value)}
              style={{ width: 260 }}
            />
            <Select
              mode="multiple"
              allowClear
              placeholder="筛选 Provider"
              value={providerFilters}
              options={providerOptions}
              onChange={(values) => setProviderFilters(values)}
              style={{ width: 220 }}
            />
            <Select
              mode="multiple"
              allowClear
              placeholder="筛选结论"
              value={conclusionFilters}
              options={conclusionOptions}
              onChange={(values) => setConclusionFilters(values)}
              style={{ width: 220 }}
            />
            <Button
              onClick={() => {
                setKeyword('')
                setProviderFilters([])
                setConclusionFilters([])
              }}
            >
              重置筛选
            </Button>
          </Space>
          <Typography.Text type="secondary">结果 {filteredItems.length} 条</Typography.Text>
        </Space>
        <Table
          rowKey={(row) => `${row.symbol}-${row.fetched_at}-${row.provider}`}
          loading={query.isLoading}
          dataSource={filteredItems}
          columns={columns}
          scroll={{ x: 1350 }}
          expandable={{
            expandedRowRender: (record) => (
              <Space orientation="vertical" size={6} style={{ width: '100%' }}>
                <Typography.Text>
                  上涨原因: {(record.rise_reasons ?? []).length > 0 ? (record.rise_reasons ?? []).join('；') : '--'}
                </Typography.Text>
                <Typography.Text type="secondary">来源:</Typography.Text>
                {(record.source_urls ?? []).length > 0 ? (
                  <Space orientation="vertical" size={2}>
                    {record.source_urls.map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer">
                        {url}
                      </a>
                    ))}
                  </Space>
                ) : (
                  <Typography.Text type="secondary">无</Typography.Text>
                )}
                {record.error_code ? (
                  <Typography.Text type="warning">降级/错误: {record.error_code}</Typography.Text>
                ) : null}
              </Space>
            ),
          }}
          pagination={{ pageSize: 6 }}
        />
      </Card>
    </Space>
  )
}

