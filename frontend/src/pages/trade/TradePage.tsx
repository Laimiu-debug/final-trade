import { useEffect, useMemo, useState } from 'react'
import dayjs, { Dayjs } from 'dayjs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '@/shared/api/client'
import {
  cancelSimOrder,
  getSimConfig,
  getSimFills,
  getSimOrders,
  postSimOrder,
  resetSim,
  settleSim,
  updateSimConfig,
} from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import { formatMoney, formatPct } from '@/shared/utils/format'
import type { SimTradeFill, SimTradeOrder, SimTradingConfig } from '@/types/contracts'

const defaultTradeFormValues: { side: 'buy' | 'sell'; quantity: number; symbol: string } = {
  side: 'buy',
  quantity: 1000,
  symbol: 'sz300750',
}

const defaultConfigValues: SimTradingConfig = {
  initial_capital: 1_000_000,
  commission_rate: 0.0003,
  min_commission: 5,
  stamp_tax_rate: 0.001,
  transfer_fee_rate: 0.00001,
  slippage_rate: 0,
}

function formatApiError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'REQUEST_TIMEOUT') {
      return '请求超时，请稍后重试。'
    }
    return error.message || `请求失败：${error.code}`
  }
  if (error instanceof Error) {
    return error.message || '请求失败'
  }
  return '请求失败'
}

function statusColor(status: SimTradeOrder['status']) {
  if (status === 'filled') return 'green'
  if (status === 'pending') return 'blue'
  if (status === 'cancelled') return 'orange'
  return 'red'
}

export function TradePage() {
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const [orderForm] = Form.useForm()
  const [configForm] = Form.useForm<SimTradingConfig>()
  const [searchParams] = useSearchParams()
  const [latestOrder, setLatestOrder] = useState<SimTradeOrder | null>(null)
  const [latestFill, setLatestFill] = useState<SimTradeFill | null>(null)
  const [orderStatus, setOrderStatus] = useState<SimTradeOrder['status'] | 'all'>('all')
  const [orderSide, setOrderSide] = useState<'all' | 'buy' | 'sell'>('all')
  const [orderSymbol, setOrderSymbol] = useState('')
  const [orderRange, setOrderRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [fillSide, setFillSide] = useState<'all' | 'buy' | 'sell'>('all')
  const [fillSymbol, setFillSymbol] = useState('')
  const [fillRange, setFillRange] = useState<[Dayjs, Dayjs] | null>(null)

  const configQuery = useQuery({
    queryKey: ['sim-config'],
    queryFn: getSimConfig,
  })

  useEffect(() => {
    if (configQuery.data) {
      configForm.setFieldsValue(configQuery.data)
    } else {
      configForm.setFieldsValue(defaultConfigValues)
    }
  }, [configForm, configQuery.data])

  const orderQuery = useQuery({
    queryKey: [
      'sim-orders',
      orderStatus,
      orderSide,
      orderSymbol,
      orderRange?.[0]?.format('YYYY-MM-DD'),
      orderRange?.[1]?.format('YYYY-MM-DD'),
    ],
    queryFn: () =>
      getSimOrders({
        status: orderStatus === 'all' ? undefined : orderStatus,
        side: orderSide === 'all' ? undefined : orderSide,
        symbol: orderSymbol.trim() || undefined,
        date_from: orderRange?.[0]?.format('YYYY-MM-DD'),
        date_to: orderRange?.[1]?.format('YYYY-MM-DD'),
        page: 1,
        page_size: 200,
      }),
  })

  const fillQuery = useQuery({
    queryKey: [
      'sim-fills',
      fillSide,
      fillSymbol,
      fillRange?.[0]?.format('YYYY-MM-DD'),
      fillRange?.[1]?.format('YYYY-MM-DD'),
    ],
    queryFn: () =>
      getSimFills({
        side: fillSide === 'all' ? undefined : fillSide,
        symbol: fillSymbol.trim() || undefined,
        date_from: fillRange?.[0]?.format('YYYY-MM-DD'),
        date_to: fillRange?.[1]?.format('YYYY-MM-DD'),
        page: 1,
        page_size: 200,
      }),
  })

  const orderMutation = useMutation({
    mutationFn: postSimOrder,
    onSuccess: (data) => {
      setLatestOrder(data.order)
      setLatestFill(data.fill ?? null)
      if (data.order.status === 'rejected') {
        message.error(data.order.reject_reason || data.order.status_reason || '订单已拒绝')
      } else {
        message.success(`订单已提交：${data.order.symbol} x ${data.order.quantity}`)
      }
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sim-orders'] }),
        queryClient.invalidateQueries({ queryKey: ['sim-fills'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['review'] }),
      ])
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) => cancelSimOrder(orderId),
    onSuccess: () => {
      message.success('撤单成功')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sim-orders'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
      ])
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const settleMutation = useMutation({
    mutationFn: settleSim,
    onSuccess: (res) => {
      message.success(`补结完成：处理 ${res.settled_count} 笔，成交 ${res.filled_count} 笔`)
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sim-orders'] }),
        queryClient.invalidateQueries({ queryKey: ['sim-fills'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['review'] }),
      ])
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const resetMutation = useMutation({
    mutationFn: resetSim,
    onSuccess: () => {
      message.success('账户已重置')
      setLatestOrder(null)
      setLatestFill(null)
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sim-orders'] }),
        queryClient.invalidateQueries({ queryKey: ['sim-fills'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['review'] }),
      ])
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  const configMutation = useMutation({
    mutationFn: updateSimConfig,
    onSuccess: () => {
      message.success('交易配置已保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sim-config'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['review'] }),
      ])
    },
    onError: (error) => {
      message.error(formatApiError(error))
    },
  })

  useEffect(() => {
    const symbol = searchParams.get('symbol')
    const side = searchParams.get('side')
    const quantity = searchParams.get('quantity')

    const patch: Partial<typeof defaultTradeFormValues> = {}
    if (symbol && symbol.trim().length >= 4) patch.symbol = symbol.trim().toLowerCase()
    if (side === 'buy' || side === 'sell') patch.side = side
    if (quantity) {
      const parsed = Number(quantity)
      if (Number.isFinite(parsed) && parsed >= 100) {
        patch.quantity = Math.round(parsed / 100) * 100
      }
    }
    if (Object.keys(patch).length > 0) {
      orderForm.setFieldsValue(patch)
    }
  }, [orderForm, searchParams])

  const orderColumns: ColumnsType<SimTradeOrder> = useMemo(
    () => [
      { title: '订单号', dataIndex: 'order_id', width: 200, ellipsis: true },
      { title: '代码', dataIndex: 'symbol', width: 120 },
      {
        title: '方向',
        dataIndex: 'side',
        width: 80,
        render: (value: SimTradeOrder['side']) => (value === 'buy' ? '买入' : '卖出'),
      },
      { title: '数量', dataIndex: 'quantity', width: 90 },
      { title: '提交日', dataIndex: 'submit_date', width: 110 },
      { title: '预计成交日', dataIndex: 'expected_fill_date', width: 120 },
      { title: '成交日', dataIndex: 'filled_date', width: 110 },
      {
        title: '状态',
        dataIndex: 'status',
        width: 90,
        render: (value: SimTradeOrder['status']) => <Tag color={statusColor(value)}>{value}</Tag>,
      },
      {
        title: '预估现金影响',
        dataIndex: 'cash_impact',
        width: 130,
        render: (value?: number) => (typeof value === 'number' ? formatMoney(value) : '-'),
      },
      {
        title: '原因',
        dataIndex: 'status_reason',
        width: 170,
        render: (_: string, row: SimTradeOrder) => row.reject_reason || row.status_reason || '-',
      },
      {
        title: '操作',
        key: 'actions',
        width: 110,
        fixed: 'right',
        render: (_: unknown, row: SimTradeOrder) => (
          <Popconfirm
            title="确认撤单？"
            disabled={row.status !== 'pending'}
            onConfirm={() => cancelMutation.mutate(row.order_id)}
          >
            <Button size="small" disabled={row.status !== 'pending'} loading={cancelMutation.isPending}>
              撤单
            </Button>
          </Popconfirm>
        ),
      },
    ],
    [cancelMutation],
  )

  const fillColumns: ColumnsType<SimTradeFill> = useMemo(
    () => [
      { title: '订单号', dataIndex: 'order_id', width: 200, ellipsis: true },
      { title: '代码', dataIndex: 'symbol', width: 120 },
      {
        title: '方向',
        dataIndex: 'side',
        width: 80,
        render: (value: SimTradeFill['side']) => (value === 'buy' ? '买入' : '卖出'),
      },
      { title: '数量', dataIndex: 'quantity', width: 90 },
      { title: '成交日', dataIndex: 'fill_date', width: 110 },
      { title: '成交价', dataIndex: 'fill_price', width: 90 },
      {
        title: '成交额',
        dataIndex: 'gross_amount',
        width: 120,
        render: (value: number) => formatMoney(value),
      },
      {
        title: '净现金',
        dataIndex: 'net_amount',
        width: 120,
        render: (value: number) => formatMoney(value),
      },
      {
        title: '手续费',
        key: 'fees',
        width: 140,
        render: (_: unknown, row: SimTradeFill) =>
          formatMoney(row.fee_commission + row.fee_stamp_tax + row.fee_transfer),
      },
      { title: '警告', dataIndex: 'warning', width: 180, render: (value?: string) => value || '-' },
    ],
    [],
  )

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="模拟交易" subtitle="A股 T+1 交易闭环：下单、撤单、补结、配置持久化与订单成交查询。" />

      <Card className="glass-card" variant="borderless">
        <Form
          layout="vertical"
          form={orderForm}
          initialValues={defaultTradeFormValues}
          onFinish={(values) =>
            orderMutation.mutate({
              ...values,
              signal_date: searchParams.get('signal_date') || dayjs().format('YYYY-MM-DD'),
              submit_date: dayjs().format('YYYY-MM-DD'),
            })
          }
        >
          <Row gutter={12}>
            <Col xs={24} md={8}>
              <Form.Item name="symbol" label="股票代码" rules={[{ required: true, message: '请输入股票代码' }]}>
                <Input placeholder="如 sz300750" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="side" label="方向" rules={[{ required: true }]}>
                <Radio.Group
                  optionType="button"
                  options={[
                    { value: 'buy', label: '买入' },
                    { value: 'sell', label: '卖出' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="quantity"
                label="数量(股)"
                rules={[
                  { required: true, message: '请输入数量' },
                  {
                    validator: (_, value: number) =>
                      value % 100 === 0
                        ? Promise.resolve()
                        : Promise.reject(new Error('仅支持100股整数倍')),
                  },
                ]}
              >
                <InputNumber min={100} step={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Space>
            <Button type="primary" htmlType="submit" loading={orderMutation.isPending}>
              提交订单
            </Button>
            <Button loading={settleMutation.isPending} onClick={() => settleMutation.mutate()}>
              手动补结
            </Button>
            <Popconfirm
              title="确认重置账户？"
              description="会清空订单、成交、持仓与复盘数据。"
              onConfirm={() => resetMutation.mutate()}
            >
              <Button danger loading={resetMutation.isPending}>
                重置账户
              </Button>
            </Popconfirm>
          </Space>
        </Form>
      </Card>

      <Card className="glass-card" variant="borderless" title="交易配置（账户全局生效）">
        <Form
          form={configForm}
          layout="vertical"
          initialValues={defaultConfigValues}
          onFinish={(values) => configMutation.mutate(values)}
        >
          <Row gutter={12}>
            <Col xs={24} md={8}>
              <Form.Item name="initial_capital" label="初始资金" rules={[{ required: true }]}>
                <InputNumber min={10_000} step={10_000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="commission_rate" label="佣金率" rules={[{ required: true }]}>
                <InputNumber min={0} max={0.01} step={0.0001} precision={6} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="min_commission" label="最低佣金" rules={[{ required: true }]}>
                <InputNumber min={0} step={1} precision={2} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="stamp_tax_rate" label="印花税率(卖出)" rules={[{ required: true }]}>
                <InputNumber min={0} max={0.01} step={0.0001} precision={6} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="transfer_fee_rate" label="过户费率" rules={[{ required: true }]}>
                <InputNumber min={0} max={0.01} step={0.00001} precision={7} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="slippage_rate" label="滑点率" rules={[{ required: true }]}>
                <InputNumber min={0} max={0.05} step={0.0001} precision={6} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Space align="center">
            <Button type="primary" htmlType="submit" loading={configMutation.isPending || configQuery.isLoading}>
              保存配置
            </Button>
            <Typography.Text type="secondary">
              当前默认费率：佣金万3（最低5元）、印花税千1（卖出）、过户费万0.1。
            </Typography.Text>
          </Space>
        </Form>
      </Card>

      {latestOrder ? (
        <Card className="glass-card" variant="borderless">
          <Space size={12} wrap>
            <Tag color="blue">{latestOrder.symbol}</Tag>
            <Tag>{latestOrder.side === 'buy' ? '买入' : '卖出'}</Tag>
            <Tag color={statusColor(latestOrder.status)}>{latestOrder.status}</Tag>
            {latestFill ? <Tag color="gold">成交价 {latestFill.fill_price}</Tag> : null}
            {typeof latestOrder.cash_impact === 'number' ? (
              <Tag color={latestOrder.cash_impact >= 0 ? 'green' : 'red'}>
                现金影响 {formatMoney(latestOrder.cash_impact)}
              </Tag>
            ) : null}
          </Space>
        </Card>
      ) : null}

      <Card className="glass-card" variant="borderless">
        <Tabs
          items={[
            {
              key: 'orders',
              label: `订单列表 (${orderQuery.data?.total ?? 0})`,
              children: (
                <Space orientation="vertical" size={12} style={{ width: '100%' }}>
                  <Row gutter={12}>
                    <Col xs={24} md={6}>
                      <Select
                        value={orderStatus}
                        style={{ width: '100%' }}
                        onChange={setOrderStatus}
                        options={[
                          { value: 'all', label: '全部状态' },
                          { value: 'pending', label: 'pending' },
                          { value: 'filled', label: 'filled' },
                          { value: 'cancelled', label: 'cancelled' },
                          { value: 'rejected', label: 'rejected' },
                        ]}
                      />
                    </Col>
                    <Col xs={24} md={6}>
                      <Select
                        value={orderSide}
                        style={{ width: '100%' }}
                        onChange={setOrderSide}
                        options={[
                          { value: 'all', label: '全部方向' },
                          { value: 'buy', label: '买入' },
                          { value: 'sell', label: '卖出' },
                        ]}
                      />
                    </Col>
                    <Col xs={24} md={6}>
                      <Input
                        value={orderSymbol}
                        placeholder="按代码筛选"
                        onChange={(event) => setOrderSymbol(event.target.value)}
                      />
                    </Col>
                    <Col xs={24} md={6}>
                      <DatePicker.RangePicker
                        value={orderRange}
                        onChange={(value) => setOrderRange((value as [Dayjs, Dayjs]) ?? null)}
                        style={{ width: '100%' }}
                      />
                    </Col>
                  </Row>
                  <Table
                    rowKey="order_id"
                    columns={orderColumns}
                    dataSource={orderQuery.data?.items ?? []}
                    loading={orderQuery.isLoading}
                    pagination={false}
                    scroll={{ x: 1400 }}
                  />
                </Space>
              ),
            },
            {
              key: 'fills',
              label: `成交列表 (${fillQuery.data?.total ?? 0})`,
              children: (
                <Space orientation="vertical" size={12} style={{ width: '100%' }}>
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Select
                        value={fillSide}
                        style={{ width: '100%' }}
                        onChange={setFillSide}
                        options={[
                          { value: 'all', label: '全部方向' },
                          { value: 'buy', label: '买入' },
                          { value: 'sell', label: '卖出' },
                        ]}
                      />
                    </Col>
                    <Col xs={24} md={8}>
                      <Input
                        value={fillSymbol}
                        placeholder="按代码筛选"
                        onChange={(event) => setFillSymbol(event.target.value)}
                      />
                    </Col>
                    <Col xs={24} md={8}>
                      <DatePicker.RangePicker
                        value={fillRange}
                        onChange={(value) => setFillRange((value as [Dayjs, Dayjs]) ?? null)}
                        style={{ width: '100%' }}
                      />
                    </Col>
                  </Row>
                  <Table
                    rowKey={(row) => `${row.order_id}-${row.fill_date}`}
                    columns={fillColumns}
                    dataSource={fillQuery.data?.items ?? []}
                    loading={fillQuery.isLoading}
                    pagination={false}
                    scroll={{ x: 1250 }}
                    summary={(data) => {
                      if (data.length === 0) return null
                      const net = data.reduce((sum, row) => sum + row.net_amount, 0)
                      return (
                        <Table.Summary.Row>
                          <Table.Summary.Cell index={0} colSpan={7}>
                            合计
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={1}>{formatMoney(net)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={2} colSpan={2}>
                            净额占初始资金{' '}
                            {configQuery.data?.initial_capital
                              ? formatPct(net / configQuery.data.initial_capital)
                              : '-'}
                          </Table.Summary.Cell>
                        </Table.Summary.Row>
                      )
                    }}
                  />
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
