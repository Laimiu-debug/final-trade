import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useMutation } from '@tanstack/react-query'
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import { postSimOrder } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { SimTradeFill, SimTradeOrder } from '@/types/contracts'

const defaultTradeFormValues: { side: 'buy' | 'sell'; quantity: number; symbol: string } = {
  side: 'buy',
  quantity: 1000,
  symbol: 'sz300750',
}

export function TradePage() {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm()
  const [searchParams] = useSearchParams()
  const [latestOrder, setLatestOrder] = useState<SimTradeOrder | null>(null)
  const [latestFill, setLatestFill] = useState<SimTradeFill | null>(null)

  const orderMutation = useMutation({
    mutationFn: postSimOrder,
    onSuccess: (data) => {
      setLatestOrder(data.order)
      setLatestFill(data.fill ?? null)
      message.success('模拟订单已成交')
    },
  })

  useEffect(() => {
    const symbol = searchParams.get('symbol')
    const side = searchParams.get('side')
    const quantity = searchParams.get('quantity')

    const patch: Partial<typeof defaultTradeFormValues> = {}
    if (symbol && symbol.trim().length >= 4) {
      patch.symbol = symbol.trim()
    }
    if (side === 'buy' || side === 'sell') {
      patch.side = side
    }
    if (quantity) {
      const parsed = Number(quantity)
      if (Number.isFinite(parsed) && parsed >= 100) {
        patch.quantity = Math.round(parsed / 100) * 100
      }
    }
    if (Object.keys(patch).length > 0) {
      form.setFieldsValue(patch)
    }
  }, [form, searchParams])

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="模拟交易" subtitle="当前为原型阶段，订单通过 MSW 或后端模拟成交。" />
      <Card className="glass-card" variant="borderless">
        <Form
          layout="vertical"
          form={form}
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
              <Form.Item name="symbol" label="股票代码">
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="side" label="方向">
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
              <Form.Item name="quantity" label="数量(股)">
                <InputNumber min={100} step={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={orderMutation.isPending}>
            提交模拟订单
          </Button>
        </Form>
      </Card>

      {latestOrder ? (
        <Card className="glass-card" variant="borderless">
          <Typography.Title level={5}>最近成交</Typography.Title>
          <Space size={12}>
            <Tag color="blue">{latestOrder.symbol}</Tag>
            <Tag>{latestOrder.side}</Tag>
            <Tag color="green">{latestOrder.status}</Tag>
            {latestFill ? <Tag color="gold">成交价 {latestFill.fill_price}</Tag> : null}
          </Space>
        </Card>
      ) : null}
    </Space>
  )
}

