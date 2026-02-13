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
  getAIRecords,
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
  const cachedAIRecord = useUIStore((state) => state.latestAIBySymbol[symbol])
  const [intradayDate, setIntradayDate] = useState<string | null>(null)
  const [intradayChartReady, setIntradayChartReady] = useState(false)
  const [lastAIRecord, setLastAIRecord] = useState<AIAnalysisRecord | null>(null)
  const cachedDraft = useUIStore((state) => state.annotationDrafts[symbol])
  const upsertDraft = useUIStore((state) => state.upsertDraft)
  const upsertLatestAIRecord = useUIStore((state) => state.upsertLatestAIRecord)
  const symbolText = symbol.toUpperCase()
  const resolvedName = stockName || lastAIRecord?.name || cachedAIRecord?.name
  const stockTitle = resolvedName ? `${resolvedName} (${symbolText})` : symbolText

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

  const aiRecordsQuery = useQuery({
    queryKey: ['ai-records'],
    queryFn: getAIRecords,
  })

  const intradayQuery = useQuery({
    queryKey: ['intraday', symbol, intradayDate],
    queryFn: () => getStockIntraday(symbol, intradayDate ?? ''),
    enabled: Boolean(symbol && intradayDate),
  })

  const { control, getValues, handleSubmit, reset, setValue, watch } = useForm<StockAnnotation>({
    defaultValues: defaultAnnotation(symbol),
  })
  const manualStartDate = watch('start_date')

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

  useEffect(() => {
    const latestFromServer = (aiRecordsQuery.data?.items ?? []).find((item) => item.symbol === symbol)
    if (latestFromServer) {
      setLastAIRecord(latestFromServer)
      upsertLatestAIRecord(latestFromServer)
      return
    }
    if (cachedAIRecord) {
      setLastAIRecord(cachedAIRecord)
    }
  }, [aiRecordsQuery.data?.items, cachedAIRecord, symbol, upsertLatestAIRecord])

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
      upsertLatestAIRecord(record)
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
    setIntradayChartReady(false)
    setIntradayDate(date)
  }

  function toTrendClassFromAIBullType(value?: string): StockAnnotation['trend_class'] {
    const raw = value ?? ''
    if (raw.includes('A_B')) return 'A_B'
    if (raw.startsWith('A')) return 'A'
    if (raw.startsWith('B')) return 'B'
    return 'Unknown'
  }

  function toStageFromConclusion(value?: string): StockAnnotation['stage'] {
    if (value === '发酵中') return 'Early'
    if (value === '高潮') return 'Mid'
    if (value === '退潮') return 'Late'
    return getValues('stage')
  }

  function applyAIToManual() {
    if (!lastAIRecord) return
    const current = getValues()
    if (lastAIRecord.breakout_date) {
      setValue('start_date', lastAIRecord.breakout_date, { shouldDirty: true })
    }
    setValue('trend_class', toTrendClassFromAIBullType(lastAIRecord.trend_bull_type), { shouldDirty: true })
    setValue('stage', toStageFromConclusion(lastAIRecord.conclusion), { shouldDirty: true })
    const aiNote = `[AI ${lastAIRecord.fetched_at}] 结论=${lastAIRecord.conclusion} 题材=${lastAIRecord.theme_name ?? '--'} 原因=${(lastAIRecord.rise_reasons ?? []).join('；')}`
    const mergedNotes = current.notes?.trim() ? `${current.notes.trim()}\n${aiNote}` : aiNote
    setValue('notes', mergedNotes, { shouldDirty: true })
    message.success('已将 AI 结论回填到人工标注，请确认后点击“保存人工标注”')
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Button icon={<ArrowLeftOutlined />} onClick={backToPrev} style={{ width: 'fit-content' }}>
        返回选股池
      </Button>
      <PageHeader
        title={`K线标注 - ${stockTitle}`}
        subtitle="K线上已叠加人工启动日与AI起爆日标记；双击K线可查看对应分时图。"
        badge="手工优先"
      />

      {analysisQuery.data?.analysis.degraded ? (
        <Alert
          type="warning"
          showIcon
          title="题材分析使用降级结果"
          description={analysisQuery.data.analysis.degraded_reason}
        />
      ) : null}

      {candlesQuery.data?.degraded ? (
        <Alert
          type="info"
          showIcon
          title="存在分钟线缺失"
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
          manualStartDate={manualStartDate}
          aiBreakoutDate={lastAIRecord?.breakout_date}
          onCandleDoubleClick={openIntradayForDate}
        />
        <Space style={{ marginTop: 10 }}>
          <Button
            size="small"
            disabled={!manualStartDate}
            onClick={() => {
              if (manualStartDate) {
                openIntradayForDate(manualStartDate)
              }
            }}
          >
            查看人工启动日分时
          </Button>
          <Button
            size="small"
            disabled={!lastAIRecord?.breakout_date}
            onClick={() => {
              if (lastAIRecord?.breakout_date) {
                openIntradayForDate(lastAIRecord.breakout_date)
              }
            }}
          >
            查看AI起爆日分时
          </Button>
        </Space>
      </Card>

      <Card
        className="glass-card"
        variant="borderless"
        title={<Typography.Text strong>标注面板</Typography.Text>}
      >
        <Space orientation="vertical" size={14} style={{ width: '100%' }}>
          <Row gutter={[16, 12]}>
            <Col xs={24} md={8}>
              <Space orientation="vertical" size={4} style={{ width: '100%' }}>
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
              <Space orientation="vertical" size={4} style={{ width: '100%' }}>
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
              <Space orientation="vertical" size={4} style={{ width: '100%' }}>
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
              <Space orientation="vertical" size={4} style={{ width: '100%' }}>
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
                analyzeMutation.mutate()
              }}
            >
              AI分析本股
            </Button>
            <Button disabled={!lastAIRecord} onClick={applyAIToManual}>
              一键应用AI到人工标注
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
              title={`AI结论: ${lastAIRecord.conclusion} | 置信度 ${lastAIRecord.confidence}`}
              description={
                <Space orientation="vertical" size={4}>
                  <Typography.Text>
                    起爆日期: {lastAIRecord.breakout_date || '--'} | 趋势牛: {lastAIRecord.trend_bull_type || '--'} | 题材: {lastAIRecord.theme_name || '--'}
                  </Typography.Text>
                  <Typography.Text>
                    上涨原因: {(lastAIRecord.rise_reasons ?? []).length > 0 ? (lastAIRecord.rise_reasons ?? []).join('；') : '--'}
                  </Typography.Text>
                  <Typography.Text>{lastAIRecord.summary}</Typography.Text>
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
        afterOpenChange={(open) => {
          setIntradayChartReady(open)
        }}
        footer={null}
        width={980}
        destroyOnHidden
      >
        {intradayQuery.data?.degraded ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            title="分时图包含近似数据"
            description={intradayQuery.data.degraded_reason}
          />
        ) : null}
        {intradayChartReady ? <IntradayChart points={intradayQuery.data?.points ?? []} /> : <div style={{ height: 420 }} />}
      </Modal>
    </Space>
  )
}

