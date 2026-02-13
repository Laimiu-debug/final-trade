import { useEffect, useMemo, useRef, useState } from 'react'
import dayjs from 'dayjs'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  InputNumber,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { LineChartOutlined, ReloadOutlined, ShoppingCartOutlined, SwapOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '@/shared/api/client'
import { getSignals, postSimOrder } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import { useUIStore } from '@/state/uiStore'
import type { SignalResult, SignalScanMode, SignalType } from '@/types/contracts'

type StatusFilter = 'active' | 'expiring' | 'expired' | 'all'

interface SignalTableRow extends SignalResult {
  key: string
  phase_label: string
  event_label: string
  event_count: number
  quality_score: number
  sequence_ok: boolean
  days_to_expire: number
  is_today_trigger: boolean
}

const signalColor: Record<SignalType, string> = {
  B: 'red',
  A: 'green',
  C: 'orange',
}

const signalWeight: Record<SignalType, number> = {
  B: 3,
  A: 2,
  C: 1,
}

function formatSignalError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'REQUEST_TIMEOUT') {
      return '待买信号请求超时，请稍后重试（全市场扫描可能需要更长时间）。'
    }
    if (error.code.startsWith('HTTP_')) {
      return `待买信号请求失败（${error.code}）：${error.message}`
    }
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return '待买信号请求失败，请检查后端服务。'
}

function buildFilters(values: string[]) {
  const unique = Array.from(new Set(values.filter((value) => value.trim().length > 0)))
  return unique
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
    .map((value) => ({ text: value, value }))
}

function parseDateValue(value: string) {
  const parsed = dayjs(value)
  if (!parsed.isValid()) return 0
  return parsed.valueOf()
}

function normalizeSignalRow(item: SignalResult, todayStart: dayjs.Dayjs): SignalTableRow {
  const trigger = dayjs(item.trigger_date).startOf('day')
  const expire = dayjs(item.expire_date).startOf('day')
  const safeTrigger = trigger.isValid() ? trigger : todayStart
  const safeExpire = expire.isValid() ? expire : safeTrigger.add(2, 'day')
  const eventCount = item.wy_event_count ?? item.wy_events?.length ?? 0
  const phaseLabel = item.wyckoff_phase?.trim() || '阶段未明'
  const eventLabel = item.wyckoff_signal?.trim() || item.wy_events?.[item.wy_events.length - 1] || '-'
  const qualityScore =
    typeof item.entry_quality_score === 'number'
      ? item.entry_quality_score
      : Math.min(99, item.priority * 25 + eventCount * 6)
  const sequenceOk = item.wy_sequence_ok ?? false
  const daysToExpire = safeExpire.diff(todayStart, 'day')
  const isTodayTrigger = safeTrigger.isSame(todayStart, 'day')

  return {
    ...item,
    key: item.symbol,
    phase_label: phaseLabel,
    event_label: eventLabel,
    event_count: eventCount,
    quality_score: qualityScore,
    sequence_ok: sequenceOk,
    days_to_expire: daysToExpire,
    is_today_trigger: isTodayTrigger,
  }
}

function renderTimelinessTag(row: SignalTableRow) {
  if (row.days_to_expire < 0) {
    return <Tag>已失效</Tag>
  }
  if (row.days_to_expire <= 1) {
    return <Tag color="orange">临期({row.days_to_expire}天)</Tag>
  }
  return <Tag color="green">有效({row.days_to_expire}天)</Tag>
}

export function SignalsPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const setSelectedSymbol = useUIStore((state) => state.setSelectedSymbol)
  const [searchParams] = useSearchParams()
  const runId = searchParams.get('run_id') ?? undefined

  const [mode, setMode] = useState<SignalScanMode>('trend_pool')
  const [windowDays, setWindowDays] = useState(60)
  const [minScore, setMinScore] = useState(60)
  const [minEventCount, setMinEventCount] = useState(1)
  const [requireSequence, setRequireSequence] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [signalFilter, setSignalFilter] = useState<'all' | SignalType>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [quickQuantity, setQuickQuantity] = useState(1000)
  const [refreshCounter, setRefreshCounter] = useState(0)
  const [manualRefreshing, setManualRefreshing] = useState(false)

  const refreshTrackerRef = useRef(0)
  const todayStartRef = useRef(dayjs().startOf('day'))

  const signalQuery = useQuery({
    queryKey: ['signals', mode, runId, windowDays, minScore, minEventCount, requireSequence, refreshCounter],
    queryFn: async () => {
      const shouldRefresh = refreshCounter > refreshTrackerRef.current
      if (shouldRefresh) {
        refreshTrackerRef.current = refreshCounter
      }
      return getSignals({
        mode,
        run_id: runId,
        refresh: shouldRefresh,
        window_days: windowDays,
        min_score: minScore,
        require_sequence: requireSequence,
        min_event_count: minEventCount,
      })
    },
    staleTime: 30_000,
  })

  useEffect(() => {
    if (!signalQuery.isFetching) {
      setManualRefreshing(false)
    }
  }, [signalQuery.isFetching])

  const quickBuyMutation = useMutation({
    mutationFn: (row: SignalTableRow) =>
      postSimOrder({
        symbol: row.symbol,
        side: 'buy',
        quantity: quickQuantity,
        signal_date: row.trigger_date,
        submit_date: dayjs().format('YYYY-MM-DD'),
      }),
    onSuccess: (_data, row) => {
      message.success(`模拟买入已提交：${row.symbol} x ${quickQuantity}`)
    },
    onError: (error) => {
      message.error(formatSignalError(error))
    },
  })

  const allRows = useMemo(
    () => (signalQuery.data?.items ?? []).map((item) => normalizeSignalRow(item, todayStartRef.current)),
    [signalQuery.data?.items],
  )

  const kpi = useMemo(() => {
    const valid = allRows.filter((row) => row.days_to_expire >= 0)
    const expiring = valid.filter((row) => row.days_to_expire <= 1)
    const expired = allRows.filter((row) => row.days_to_expire < 0)
    const todayTriggered = allRows.filter((row) => row.is_today_trigger)
    const bSignals = allRows.filter((row) => row.primary_signal === 'B')
    return {
      valid: valid.length,
      expiring: expiring.length,
      expired: expired.length,
      todayTriggered: todayTriggered.length,
      bSignals: bSignals.length,
      sourceCount: signalQuery.data?.source_count ?? allRows.length,
    }
  }, [allRows, signalQuery.data?.source_count])

  const filteredRows = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()
    return allRows.filter((row) => {
      if (signalFilter !== 'all' && row.primary_signal !== signalFilter) {
        return false
      }
      if (statusFilter === 'active' && row.days_to_expire < 0) {
        return false
      }
      if (statusFilter === 'expiring' && (row.days_to_expire < 0 || row.days_to_expire > 1)) {
        return false
      }
      if (statusFilter === 'expired' && row.days_to_expire >= 0) {
        return false
      }
      if (!normalizedKeyword) {
        return true
      }
      const haystack = [
        row.symbol,
        row.name,
        row.trigger_reason,
        row.phase_label,
        row.event_label,
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(normalizedKeyword)
    })
  }, [allRows, keyword, signalFilter, statusFilter])

  const primarySignalFilters = useMemo(
    () =>
      (['B', 'A', 'C'] as SignalType[])
        .filter((signal) => allRows.some((row) => row.primary_signal === signal))
        .map((signal) => ({ text: signal, value: signal })),
    [allRows],
  )

  const phaseFilters = useMemo(() => buildFilters(allRows.map((row) => row.phase_label)), [allRows])
  const eventFilters = useMemo(() => buildFilters(allRows.map((row) => row.event_label)), [allRows])

  const columns = useMemo<ColumnsType<SignalTableRow>>(
    () => [
      {
        title: '代码',
        dataIndex: 'symbol',
        width: 110,
        fixed: 'left',
        sorter: (a, b) => a.symbol.localeCompare(b.symbol, 'zh-CN'),
      },
      {
        title: '名称',
        dataIndex: 'name',
        width: 120,
        ellipsis: true,
        sorter: (a, b) => a.name.localeCompare(b.name, 'zh-CN'),
      },
      {
        title: '主信号',
        dataIndex: 'primary_signal',
        width: 92,
        filters: primarySignalFilters,
        onFilter: (value, row) => row.primary_signal === String(value),
        sorter: (a, b) => signalWeight[a.primary_signal] - signalWeight[b.primary_signal],
        render: (value: SignalType) => <Tag color={signalColor[value]}>{value}</Tag>,
      },
      {
        title: '阶段',
        key: 'phase_label',
        width: 130,
        ellipsis: true,
        filters: phaseFilters,
        onFilter: (value, row) => row.phase_label === String(value),
        sorter: (a, b) => a.phase_label.localeCompare(b.phase_label, 'zh-CN'),
        render: (_, row) => row.phase_label,
      },
      {
        title: '主事件',
        key: 'event_label',
        width: 110,
        filters: eventFilters,
        onFilter: (value, row) => row.event_label === String(value),
        sorter: (a, b) => a.event_label.localeCompare(b.event_label, 'zh-CN'),
        render: (_, row) => row.event_label,
      },
      {
        title: '评分',
        key: 'quality_score',
        width: 90,
        sorter: (a, b) => a.quality_score - b.quality_score,
        defaultSortOrder: 'descend',
        render: (_, row) => row.quality_score.toFixed(1),
      },
      {
        title: '事件数',
        key: 'event_count',
        width: 88,
        sorter: (a, b) => a.event_count - b.event_count,
        render: (_, row) => row.event_count,
      },
      {
        title: '序列完整',
        key: 'sequence_ok',
        width: 96,
        filters: [
          { text: '是', value: 'yes' },
          { text: '否', value: 'no' },
        ],
        onFilter: (value, row) => (value === 'yes' ? row.sequence_ok : !row.sequence_ok),
        sorter: (a, b) => Number(a.sequence_ok) - Number(b.sequence_ok),
        render: (_, row) => (row.sequence_ok ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
      },
      {
        title: '时效',
        key: 'timeliness',
        width: 120,
        sorter: (a, b) => a.days_to_expire - b.days_to_expire,
        render: (_, row) => renderTimelinessTag(row),
      },
      {
        title: '触发日',
        dataIndex: 'trigger_date',
        width: 112,
        sorter: (a, b) => parseDateValue(a.trigger_date) - parseDateValue(b.trigger_date),
      },
      {
        title: '操作',
        key: 'actions',
        width: 240,
        fixed: 'right',
        render: (_, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              icon={<LineChartOutlined />}
              onClick={() => {
                const params = new URLSearchParams({
                  signal_mode: mode,
                  signal_window_days: String(windowDays),
                  signal_min_score: String(minScore),
                  signal_min_event_count: String(minEventCount),
                  signal_require_sequence: String(requireSequence),
                })
                if (runId) {
                  params.set('signal_run_id', runId)
                }
                if (row.name) {
                  params.set('signal_stock_name', row.name)
                }
                setSelectedSymbol(row.symbol, row.name)
                navigate(`/stocks/${row.symbol}/chart?${params.toString()}`)
              }}
            >
              查看K线
            </Button>
            <Button
              type="link"
              size="small"
              icon={<ShoppingCartOutlined />}
              loading={quickBuyMutation.isPending}
              onClick={() => quickBuyMutation.mutate(row)}
            >
              模拟买入
            </Button>
            <Button
              type="link"
              size="small"
              icon={<SwapOutlined />}
              onClick={() =>
                navigate(
                  `/trade?symbol=${encodeURIComponent(row.symbol)}&side=buy&quantity=${quickQuantity}&signal_date=${row.trigger_date}`,
                )
              }
            >
              去交易页
            </Button>
          </Space>
        ),
      },
    ],
    [
      eventFilters,
      minEventCount,
      minScore,
      mode,
      navigate,
      phaseFilters,
      primarySignalFilters,
      quickBuyMutation,
      quickQuantity,
      requireSequence,
      runId,
      windowDays,
    ],
  )

  const expandedRowRender = (row: SignalTableRow) => (
    <Space orientation="vertical" size={8} style={{ width: '100%' }}>
      <Space size={[6, 6]} wrap>
        <Typography.Text type="secondary">事件序列</Typography.Text>
        {(row.wy_events ?? []).length > 0
          ? (row.wy_events ?? []).map((event) => (
              <Tag key={`${row.symbol}-${event}`} color="blue">
                {event}
              </Tag>
            ))
          : <Tag>-</Tag>}
      </Space>
      <Space size={[6, 6]} wrap>
        <Typography.Text type="secondary">风险事件</Typography.Text>
        {(row.wy_risk_events ?? []).length > 0
          ? (row.wy_risk_events ?? []).map((event) => (
              <Tag key={`${row.symbol}-risk-${event}`} color="red">
                {event}
              </Tag>
            ))
          : <Tag color="green">无</Tag>}
      </Space>
      <Typography.Text type="secondary">
        {row.phase_hint || row.trigger_reason || '无阶段提示'}
      </Typography.Text>
      <Space size={[6, 6]} wrap>
        <Tag>事件强度 {Number(row.event_strength_score ?? 0).toFixed(1)}</Tag>
        <Tag>阶段评分 {Number(row.phase_score ?? 0).toFixed(1)}</Tag>
        <Tag>结构评分 {Number(row.structure_score ?? 0).toFixed(1)}</Tag>
        <Tag>趋势评分 {Number(row.trend_score ?? 0).toFixed(1)}</Tag>
        <Tag>波动评分 {Number(row.volatility_score ?? 0).toFixed(1)}</Tag>
      </Space>
    </Space>
  )

  const handleForceRefresh = () => {
    setManualRefreshing(true)
    setRefreshCounter((previous) => previous + 1)
  }

  const errorMessage = signalQuery.error ? formatSignalError(signalQuery.error) : ''

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        title="待买信号（威科夫增强）"
        subtitle="默认趋势池后置模式；支持全市场扫描与阶段/事件评分。"
        badge="Wyckoff"
      />

      {errorMessage ? (
        <Alert
          type="error"
          showIcon
          message="信号加载失败"
          description={errorMessage}
        />
      ) : null}

      {signalQuery.data?.degraded ? (
        <Alert
          type="warning"
          showIcon
          message="当前结果处于降级模式"
          description={signalQuery.data.degraded_reason ?? '数据源部分不可用，已使用降级结果。'}
        />
      ) : null}

      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="有效信号" value={kpi.valid} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="临期(<=1天)" value={kpi.expiring} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="已失效" value={kpi.expired} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="今日触发" value={kpi.todayTriggered} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="B类主信号" value={kpi.bSignals} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card className="glass-card" variant="borderless">
            <Statistic title="源候选数" value={kpi.sourceCount} />
          </Card>
        </Col>
      </Row>

      <Card className="glass-card" variant="borderless">
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12} lg={8}>
              <Typography.Text type="secondary">扫描模式</Typography.Text>
              <div>
                <Radio.Group
                  value={mode}
                  onChange={(event) => setMode(event.target.value as SignalScanMode)}
                  optionType="button"
                  options={[
                    { label: '趋势池后置', value: 'trend_pool' },
                    { label: '全市场扫描', value: 'full_market' },
                  ]}
                />
              </div>
            </Col>
            <Col xs={24} md={12} lg={4}>
              <Typography.Text type="secondary">窗口(天)</Typography.Text>
              <InputNumber
                value={windowDays}
                min={20}
                max={240}
                style={{ width: '100%' }}
                onChange={(value) => {
                  if (typeof value === 'number' && Number.isFinite(value)) {
                    setWindowDays(Math.round(value))
                  }
                }}
              />
            </Col>
            <Col xs={24} md={12} lg={4}>
              <Typography.Text type="secondary">最低评分</Typography.Text>
              <InputNumber
                value={minScore}
                min={0}
                max={100}
                style={{ width: '100%' }}
                onChange={(value) => {
                  if (typeof value === 'number' && Number.isFinite(value)) {
                    setMinScore(value)
                  }
                }}
              />
            </Col>
            <Col xs={24} md={12} lg={4}>
              <Typography.Text type="secondary">最少事件数</Typography.Text>
              <InputNumber
                value={minEventCount}
                min={1}
                max={12}
                style={{ width: '100%' }}
                onChange={(value) => {
                  if (typeof value === 'number' && Number.isFinite(value)) {
                    setMinEventCount(Math.round(value))
                  }
                }}
              />
            </Col>
            <Col xs={24} md={12} lg={4}>
              <Typography.Text type="secondary">条件</Typography.Text>
              <div style={{ marginTop: 8 }}>
                <Checkbox
                  checked={requireSequence}
                  onChange={(event) => setRequireSequence(event.target.checked)}
                >
                  要求序列完整
                </Checkbox>
              </div>
            </Col>
          </Row>

          <Row gutter={[12, 12]} align="middle">
            <Col xs={24} lg={8}>
              <Input
                allowClear
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索代码/名称/触发依据"
              />
            </Col>
            <Col xs={24} lg={8}>
              <Radio.Group
                value={signalFilter}
                onChange={(event) => setSignalFilter(event.target.value as 'all' | SignalType)}
                optionType="button"
                options={[
                  { label: '全部信号', value: 'all' },
                  { label: 'B', value: 'B' },
                  { label: 'A', value: 'A' },
                  { label: 'C', value: 'C' },
                ]}
              />
            </Col>
            <Col xs={24} lg={8}>
              <Radio.Group
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                optionType="button"
                options={[
                  { label: '有效(含临期)', value: 'active' },
                  { label: '临期', value: 'expiring' },
                  { label: '已失效', value: 'expired' },
                  { label: '全部', value: 'all' },
                ]}
              />
            </Col>
          </Row>

          <Row justify="space-between" gutter={[12, 12]}>
            <Col xs={24} lg={12}>
              <Typography.Text type="secondary">
                生成时间 {signalQuery.data?.generated_at ?? '--'}
                {signalQuery.data?.cache_hit ? '（缓存命中）' : '（实时计算）'}
              </Typography.Text>
            </Col>
            <Col xs={24} lg={12}>
              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Typography.Text type="secondary">快捷买入数量</Typography.Text>
                <InputNumber
                  min={100}
                  step={100}
                  value={quickQuantity}
                  onChange={(value) => {
                    if (typeof value === 'number' && Number.isFinite(value) && value >= 100) {
                      setQuickQuantity(Math.round(value / 100) * 100)
                    }
                  }}
                />
                <Button
                  icon={<ReloadOutlined />}
                  loading={manualRefreshing && signalQuery.isFetching}
                  onClick={handleForceRefresh}
                >
                  手动刷新（重算）
                </Button>
              </Space>
            </Col>
          </Row>
        </Space>
      </Card>

      <Card className="glass-card" variant="borderless">
        <Table
          rowKey="key"
          loading={signalQuery.isLoading || signalQuery.isFetching}
          dataSource={filteredRows}
          columns={columns}
          scroll={{ x: 1480 }}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          expandable={{ expandedRowRender }}
          locale={{
            emptyText: signalQuery.isLoading ? '信号计算中...' : <Empty description="没有匹配的待买信号" />,
          }}
        />
      </Card>
    </Space>
  )
}
