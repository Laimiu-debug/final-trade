import { useEffect, useState } from 'react'
import dayjs from 'dayjs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App as AntdApp,
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Input,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { Controller, useForm } from 'react-hook-form'
import { useNavigate, useParams } from 'react-router-dom'
import {
  analyzeStockWithAI,
  getSignals,
  getStockAnalysis,
  getStockCandles,
  getStockIntraday,
  updateStockAnnotation,
} from '@/shared/api/endpoints'
import { IntradayChart } from '@/shared/charts/IntradayChart'
import { KLineChart } from '@/shared/charts/KLineChart'
import { PageHeader } from '@/shared/components/PageHeader'
import { useUIStore } from '@/state/uiStore'
import type { AIAnalysisRecord, StockAnnotation } from '@/types/contracts'

function defaultAnnotation(symbol: string): StockAnnotation {
  return {
    symbol,
    start_date: dayjs().subtract(45, 'day').format('YYYY-MM-DD'),
    stage: 'Mid',
    trend_class: 'A',
    decision: '保留',
    notes: '',
    updated_by: 'manual',
  }
}

export function ChartPage() {
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const symbol = useParams().symbol ?? ''
  const stockName = useUIStore((state) => state.stockNameMap[symbol])
  const [intradayDate, setIntradayDate] = useState<string | null>(null)
  const [lastAIRecord, setLastAIRecord] = useState<AIAnalysisRecord | null>(null)
  const cachedDraft = useUIStore((state) => state.annotationDrafts[symbol])
  const upsertDraft = useUIStore((state) => state.upsertDraft)
  const symbolText = symbol.toUpperCase()
  const stockTitle = stockName ? `${stockName} (${symbolText})` : symbolText

  const candlesQuery = useQuery({
    queryKey: ['candles', symbol],
    queryFn: () => getStockCandles(symbol),
    enabled: Boolean(symbol),
  })

  const analysisQuery = useQuery({
    queryKey: ['analysis', symbol],
    queryFn: () => getStockAnalysis(symbol),
    enabled: Boolean(symbol),
  })

  const signalsQuery = useQuery({
    queryKey: ['signals'],
    queryFn: getSignals,
  })

  const intradayQuery = useQuery({
    queryKey: ['intraday', symbol, intradayDate],
    queryFn: () => getStockIntraday(symbol, intradayDate ?? ''),
    enabled: Boolean(symbol && intradayDate),
  })

  const { control, handleSubmit, reset } = useForm<StockAnnotation>({
    defaultValues: defaultAnnotation(symbol),
  })

  useEffect(() => {
    if (!analysisQuery.data) return
    const serverAnnotation = analysisQuery.data.annotation
    const fallback = defaultAnnotation(symbol)
    reset(
      cachedDraft ?? {
        ...fallback,
        start_date: serverAnnotation?.start_date ?? analysisQuery.data.analysis.suggest_start_date,
        stage: serverAnnotation?.stage ?? analysisQuery.data.analysis.suggest_stage,
        trend_class: serverAnnotation?.trend_class ?? analysisQuery.data.analysis.suggest_trend_class,
        decision: serverAnnotation?.decision ?? '保留',
        notes: serverAnnotation?.notes ?? '',
      },
    )
  }, [analysisQuery.data, cachedDraft, reset, symbol])

  const saveMutation = useMutation({
    mutationFn: (payload: StockAnnotation) => updateStockAnnotation(symbol, payload),
    onSuccess: (_, payload) => {
      upsertDraft(payload)
      void queryClient.invalidateQueries({ queryKey: ['analysis', symbol] })
      message.success('已保存图上标注（手工优先）')
    },
  })

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeStockWithAI(symbol),
    onSuccess: (record) => {
      setLastAIRecord(record)
      void queryClient.invalidateQueries({ queryKey: ['analysis', symbol] })
      void queryClient.invalidateQueries({ queryKey: ['ai-records'] })
      message.success('AI分析完成')
    },
    onError: () => {
      message.error('AI分析失败，请稍后重试')
    },
  })

  const symbolSignals = (signalsQuery.data?.items ?? []).filter((item) => item.symbol === symbol)

  function backToPrev() {
    if (window.history.length > 1) {
      navigate(-1)
      return
    }
    navigate('/screener')
  }

  function openIntradayForDate(date: string) {
    setIntradayDate(date)
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Button icon={<ArrowLeftOutlined />} onClick={backToPrev} style={{ width: 'fit-content' }}>
        返回选股池
      </Button>
      <PageHeader
        title={`K线标注 - ${stockTitle}`}
        subtitle="支持启动日、阶段、趋势类型和交易决策的人工覆盖；双击K线可查看对应分时图。"
        badge="手工优先"
      />

      {analysisQuery.data?.analysis.degraded ? (
        <Alert
          type="warning"
          showIcon
          message="题材分析使用降级结果"
          description={analysisQuery.data.analysis.degraded_reason}
        />
      ) : null}

      {candlesQuery.data?.degraded ? (
        <Alert
          type="info"
          showIcon
          message="存在分钟线缺失"
          description={`${candlesQuery.data.degraded_reason}，已使用近似价 price_source=approx`}
        />
      ) : null}

      <Card
        className="glass-card"
        variant="borderless"
        title={
          <Space size={8}>
            <Typography.Text strong>日线K线图</Typography.Text>
            <Tag color="processing">{stockTitle}</Tag>
          </Space>
        }
      >
        <KLineChart
          candles={candlesQuery.data?.candles ?? []}
          signals={symbolSignals}
          onCandleDoubleClick={openIntradayForDate}
        />
      </Card>

      <Card
        className="glass-card"
        variant="borderless"
        title={<Typography.Text strong>标注面板</Typography.Text>}
      >
        <Space orientation="vertical" size={14} style={{ width: '100%' }}>
          <Row gutter={[16, 12]}>
            <Col xs={24} md={8}>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Typography.Text type="secondary">启动日</Typography.Text>
                <Controller
                  name="start_date"
                  control={control}
                  render={({ field }) => (
                    <DatePicker
                      style={{ width: '100%' }}
                      value={field.value ? dayjs(field.value) : null}
                      onChange={(value) => field.onChange(value?.format('YYYY-MM-DD'))}
                      allowClear={false}
                    />
                  )}
                />
              </Space>
            </Col>
            <Col xs={12} md={4}>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Typography.Text type="secondary">阶段</Typography.Text>
                <Controller
                  name="stage"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onChange={field.onChange}
                      options={[
                        { value: 'Early', label: '早期 (Early)' },
                        { value: 'Mid', label: '中期 (Mid)' },
                        { value: 'Late', label: '后期 (Late)' },
                      ]}
                    />
                  )}
                />
              </Space>
            </Col>
            <Col xs={12} md={4}>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Typography.Text type="secondary">趋势类型</Typography.Text>
                <Controller
                  name="trend_class"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onChange={field.onChange}
                      options={[
                        { value: 'A', label: 'A 阶梯慢牛' },
                        { value: 'A_B', label: 'A_B 慢牛加速' },
                        { value: 'B', label: 'B 脉冲涨停' },
                        { value: 'Unknown', label: 'Unknown 未识别' },
                      ]}
                    />
                  )}
                />
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Typography.Text type="secondary">交易决策</Typography.Text>
                <Controller
                  name="decision"
                  control={control}
                  render={({ field }) => (
                    <Radio.Group
                      value={field.value}
                      onChange={(evt) => field.onChange(evt.target.value)}
                      options={[
                        { label: '保留', value: '保留' },
                        { label: '排除', value: '排除' },
                      ]}
                      optionType="button"
                    />
                  )}
                />
              </Space>
            </Col>
          </Row>

          <Controller
            name="notes"
            control={control}
            render={({ field }) => (
              <Input.TextArea
                value={field.value}
                onChange={field.onChange}
                rows={3}
                placeholder="记录人工判断理由"
              />
            )}
          />

          <Space>
            <Button
              loading={analyzeMutation.isPending}
              onClick={() => {
                void analyzeMutation.mutateAsync()
              }}
            >
              AI分析本股
            </Button>
            <Button
              type="primary"
              loading={saveMutation.isPending}
              onClick={handleSubmit((values) =>
                saveMutation.mutate({
                  ...values,
                  symbol,
                  updated_by: 'manual',
                }),
              )}
            >
              保存人工标注
            </Button>
            <Tag color="green">manual &gt; auto</Tag>
            <Tag color="blue">confidence {analysisQuery.data?.analysis.confidence ?? '-'}</Tag>
          </Space>
          {lastAIRecord ? (
            <Alert
              type={lastAIRecord.error_code ? 'warning' : 'success'}
              showIcon
              message={`AI结论: ${lastAIRecord.conclusion} | 置信度 ${lastAIRecord.confidence}`}
              description={
                <Space direction="vertical" size={4}>
                  <Typography.Text>{lastAIRecord.summary}</Typography.Text>
                  <Typography.Text type="secondary">
                    来源: {lastAIRecord.source_urls.join(' | ') || '无'}
                  </Typography.Text>
                  {lastAIRecord.error_code ? (
                    <Typography.Text type="warning">
                      回退原因: {lastAIRecord.error_code}
                    </Typography.Text>
                  ) : null}
                </Space>
              }
            />
          ) : null}
        </Space>
      </Card>

      <Modal
        title={`${stockTitle} ${intradayQuery.data?.date ?? intradayDate ?? ''} 分时图`}
        open={Boolean(intradayDate)}
        onCancel={() => setIntradayDate(null)}
        footer={null}
        width={980}
        destroyOnClose
      >
        {intradayQuery.data?.degraded ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="分时图包含近似数据"
            description={intradayQuery.data.degraded_reason}
          />
        ) : null}
        <IntradayChart points={intradayQuery.data?.points ?? []} />
      </Modal>
    </Space>
  )
}

