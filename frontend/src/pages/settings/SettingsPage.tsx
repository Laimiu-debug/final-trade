import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Controller, useFieldArray, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { getConfig, getSystemStorage, testAIProvider, updateConfig } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { AppConfig } from '@/types/contracts'

const providerSchema = z
  .object({
    id: z.string().min(1, 'ID 必填'),
    label: z.string().min(1, '名称必填'),
    base_url: z.string().url('请输入有效 URL'),
    model: z.string().min(1, '模型必填'),
    api_key: z.string(),
    api_key_path: z.string(),
    enabled: z.boolean(),
  })
  .superRefine((value, ctx) => {
    const hasInlineKey = value.api_key.trim().length > 0
    const hasPath = value.api_key_path.trim().length > 0
    if (!hasInlineKey && !hasPath) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: '请至少填写 API 密钥 或 API Key 路径',
        path: ['api_key'],
      })
    }
  })

const sourceSchema = z.object({
  id: z.string().min(1, 'ID 必填'),
  name: z.string().min(1, '名称必填'),
  url: z.string().url('请输入有效 URL'),
  enabled: z.boolean(),
})

const schema = z.object({
  tdx_data_path: z.string().min(3),
  market_data_source: z.enum(['tdx_only', 'tdx_then_akshare', 'akshare_only']),
  akshare_cache_dir: z.string(),
  markets: z.array(z.enum(['sh', 'sz', 'bj'])).min(1),
  return_window_days: z.number().min(5).max(120),
  candles_window_bars: z.number().int().min(120).max(5000),
  top_n: z.number().min(100).max(2000),
  turnover_threshold: z.number().min(0.01).max(0.2),
  amount_threshold: z.number().min(5e7).max(5e9),
  amplitude_threshold: z.number().min(0.01).max(0.15),
  initial_capital: z.number().min(10_000).max(100_000_000),
  ai_provider: z.string().min(1),
  ai_timeout_sec: z.number().min(3).max(60),
  ai_retry_count: z.number().min(0).max(5),
  api_key: z.string(),
  api_key_path: z.string(),
  ai_providers: z.array(providerSchema).min(1, '至少保留一个 AI Provider'),
  ai_sources: z.array(sourceSchema).min(1, '至少保留一个信息源'),
})

type FormValues = z.infer<typeof schema>

function newProvider(nextIndex: number): FormValues['ai_providers'][number] {
  return {
    id: `custom-${nextIndex}`,
    label: `自定义Provider-${nextIndex}`,
    base_url: 'https://your-provider.example.com/v1',
    model: 'custom-model',
    api_key: '',
    api_key_path: '%USERPROFILE%\\.tdx-trend\\custom.key',
    enabled: true,
  }
}

function newSource(nextIndex: number): FormValues['ai_sources'][number] {
  return {
    id: `source-${nextIndex}`,
    name: `自定义信息源-${nextIndex}`,
    url: 'https://example.com/',
    enabled: true,
  }
}

const DEFAULT_FORM_VALUES: FormValues = {
  tdx_data_path: 'D:\\new_tdx\\vipdoc',
  market_data_source: 'tdx_then_akshare',
  akshare_cache_dir: '%USERPROFILE%\\.tdx-trend\\akshare\\daily',
  markets: ['sh', 'sz'],
  return_window_days: 40,
  candles_window_bars: 120,
  top_n: 500,
  turnover_threshold: 0.05,
  amount_threshold: 5e8,
  amplitude_threshold: 0.03,
  initial_capital: 1_000_000,
  ai_provider: 'openai',
  ai_timeout_sec: 10,
  ai_retry_count: 2,
  api_key: '',
  api_key_path: '',
  ai_providers: [newProvider(1)],
  ai_sources: [newSource(1)],
}

export function SettingsPage() {
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const isMockEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === 'true'
  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  })
  const storageQuery = useQuery({
    queryKey: ['system-storage'],
    queryFn: getSystemStorage,
  })

  const { control, getValues, handleSubmit, reset, setValue } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_FORM_VALUES,
  })
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null)

  const providerArray = useFieldArray({
    control,
    name: 'ai_providers',
  })

  const sourceArray = useFieldArray({
    control,
    name: 'ai_sources',
  })

  const providers =
    useWatch({
      control,
      name: 'ai_providers',
    }) ?? []

  const providerOptions = providers.map((provider) => ({
    label: `${provider.label} (${provider.id})`,
    value: provider.id,
  }))

  useEffect(() => {
    if (!configQuery.data) return
    reset({
      ...DEFAULT_FORM_VALUES,
      ...configQuery.data,
      api_key: '',
      api_key_path: '',
    })
  }, [configQuery.data, reset])

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => updateConfig(values as AppConfig),
    onSuccess: () => {
      message.success('配置已保存')
      void queryClient.invalidateQueries({ queryKey: ['config'] })
      void queryClient.invalidateQueries({ queryKey: ['system-storage'] })
    },
  })

  function validateAndSave(values: FormValues) {
    const hasCredential = (provider: FormValues['ai_providers'][number]) =>
      provider.api_key.trim().length > 0 || provider.api_key_path.trim().length > 0

    const providerIdSet = new Set<string>()
    for (const provider of values.ai_providers) {
      if (providerIdSet.has(provider.id)) {
        message.error(`Provider ID 重复: ${provider.id}`)
        return
      }
      providerIdSet.add(provider.id)

      if (provider.enabled && !hasCredential(provider)) {
        message.error(`Provider ${provider.id} 缺少凭证，请填写 API 密钥或 Key 路径`)
        return
      }
    }

    const activeProvider = values.ai_providers.find((provider) => provider.id === values.ai_provider)
    if (!activeProvider) {
      message.error('当前激活 Provider 不存在，请重新选择')
      return
    }
    if (!activeProvider.enabled) {
      message.error('当前激活 Provider 已禁用，请切换到可用 Provider')
      return
    }
    if (!hasCredential(activeProvider)) {
      message.error('当前激活 Provider 缺少凭证，请填写 API 密钥或 Key 路径')
      return
    }

    saveMutation.mutate({
      ...values,
      api_key: '',
      api_key_path: '',
    })
  }

  async function handleProviderTest(index: number) {
    const values = getValues()
    const provider = values.ai_providers[index]
    if (!provider) {
      message.error('Provider 不存在')
      return
    }

    setTestingProviderId(provider.id)
    try {
      const result = await testAIProvider({
        provider,
        fallback_api_key: '',
        fallback_api_key_path: '',
        timeout_sec: values.ai_timeout_sec,
      })
      if (result.ok) {
        message.success(`[${provider.id}] ${result.message}`)
      } else {
        message.warning(`[${provider.id}] ${result.message}${result.error_code ? ` (${result.error_code})` : ''}`)
      }
    } catch {
      message.error(`[${provider.id}] 测试失败，请检查网络与配置`)
    } finally {
      setTestingProviderId(null)
    }
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="系统设置" subtitle="支持自定义 AI Provider 与信息源，满足多来源接入。" />
      {isMockEnabled ? (
        <Alert
          type="warning"
          showIcon
          title="当前启用了 MSW Mock 模式，交易/复盘/AI 记录不会写入真实后端持久化文件。"
        />
      ) : null}
      <Card className="glass-card" variant="borderless">
        <Form layout="vertical" onFinish={handleSubmit(validateAndSave)}>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="TDX 数据路径">
                <Controller
                  name="tdx_data_path"
                  control={control}
                  render={({ field }) => <Input {...field} />}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label="行情数据源策略">
                <Controller
                  name="market_data_source"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onChange={field.onChange}
                      options={[
                        { label: '优先 TDX，缺失回退 AkShare（推荐）', value: 'tdx_then_akshare' },
                        { label: '仅 TDX', value: 'tdx_only' },
                        { label: '仅 AkShare 缓存', value: 'akshare_only' },
                      ]}
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label="本地行情目录（CSV）">
                <Controller
                  name="akshare_cache_dir"
                  control={control}
                  render={({ field }) => (
                    <Input
                      {...field}
                      placeholder="%USERPROFILE%\\.tdx-trend\\market-data\\daily"
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label="本地行情目录候选">
                <Select
                  allowClear
                  showSearch
                  placeholder={
                    storageQuery.data?.akshare_cache_candidates.length
                      ? '从已发现目录中选择'
                      : '暂无已发现目录，可手动填写'
                  }
                  options={(storageQuery.data?.akshare_cache_candidates ?? []).map((value) => ({
                    value,
                    label: value,
                  }))}
                  onChange={(value) => setValue('akshare_cache_dir', value || '')}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label="市场">
                <Controller
                  name="markets"
                  control={control}
                  render={({ field }) => (
                    <Checkbox.Group
                      value={field.value}
                      onChange={(value) => field.onChange(value as FormValues['markets'])}
                      options={[
                        { label: '沪市', value: 'sh' },
                        { label: '深市', value: 'sz' },
                        { label: '北交所', value: 'bj' },
                      ]}
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label="激活 AI Provider">
                <Controller
                  name="ai_provider"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onChange={field.onChange}
                      options={providerOptions}
                      placeholder="请选择激活 Provider"
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={12} md={6}>
              <Form.Item label="AI 超时(秒)">
                <Controller
                  name="ai_timeout_sec"
                  control={control}
                  render={({ field }) => (
                    <InputNumber
                      min={3}
                      max={60}
                      value={field.value}
                      onChange={(v) => field.onChange(v ?? 10)}
                      style={{ width: '100%' }}
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={12} md={6}>
              <Form.Item label="AI 重试次数">
                <Controller
                  name="ai_retry_count"
                  control={control}
                  render={({ field }) => (
                    <InputNumber
                      min={0}
                      max={5}
                      value={field.value}
                      onChange={(v) => field.onChange(v ?? 2)}
                      style={{ width: '100%' }}
                    />
                  )}
                />
              </Form.Item>
            </Col>

            <Col xs={12} md={6}>
              <Form.Item label="模拟初始资金">
                <Controller
                  name="initial_capital"
                  control={control}
                  render={({ field }) => (
                    <InputNumber
                      min={10_000}
                      max={100_000_000}
                      step={10_000}
                      value={field.value}
                      onChange={(v) => field.onChange(v ?? 1_000_000)}
                      style={{ width: '100%' }}
                    />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="K线读取窗口(根)">
                <Controller
                  name="candles_window_bars"
                  control={control}
                  render={({ field }) => (
                    <InputNumber
                      min={120}
                      max={5000}
                      step={60}
                      value={field.value}
                      onChange={(v) => field.onChange(v ?? 120)}
                      style={{ width: '100%' }}
                    />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={24}>
              <Typography.Text type="secondary">
                行情数据源可选 TDX 或本地行情目录回退（可由 AkShare/Baostock 生成 CSV）。漏斗参数（涨幅窗口、TopN、20日阈值）已统一在选股漏斗页面配置，此处仅保留系统级参数。
              </Typography.Text>
              <br />
              <Typography.Text type="secondary">
                本地状态: 配置{storageQuery.data?.app_state_exists ? '已持久化' : '未持久化'}，
                模拟账户{storageQuery.data?.sim_state_exists ? '已持久化' : '未持久化'}，
                本地行情文件数 {storageQuery.data?.akshare_cache_file_count ?? 0}。
              </Typography.Text>
            </Col>
          </Row>

          <Divider titlePlacement="start">AI Provider 列表</Divider>
          <Space orientation="vertical" size={12} style={{ width: '100%' }}>
            {providerArray.fields.map((item, index) => (
              <Card key={item.id} className="glass-card" size="small" variant="borderless">
                <Row gutter={[10, 10]}>
                  <Col xs={24} md={6}>
                    <Form.Item label="Provider ID">
                      <Controller
                        name={`ai_providers.${index}.id`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="显示名称">
                      <Controller
                        name={`ai_providers.${index}.label`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item label="Base URL">
                      <Controller
                        name={`ai_providers.${index}.base_url`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={4}>
                    <Form.Item label="启用">
                      <Controller
                        name={`ai_providers.${index}.enabled`}
                        control={control}
                        render={({ field }) => (
                          <Switch
                            checked={Boolean(field.value)}
                            onChange={field.onChange}
                            checkedChildren="开"
                            unCheckedChildren="关"
                          />
                        )}
                      />
                    </Form.Item>
                  </Col>

                  <Col xs={24} md={6}>
                    <Form.Item label="默认模型">
                      <Controller
                        name={`ai_providers.${index}.model`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={9}>
                    <Form.Item label="API 密钥（可选）">
                      <Controller
                        name={`ai_providers.${index}.api_key`}
                        control={control}
                        render={({ field }) => <Input.Password {...field} placeholder="直接填写优先使用" />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={9}>
                    <Form.Item label="API Key 路径（可选）">
                      <Controller
                        name={`ai_providers.${index}.api_key_path`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Space>
                  <Button
                    onClick={() => {
                      void handleProviderTest(index)
                    }}
                    loading={testingProviderId === (providers[index]?.id ?? '')}
                  >
                    测试可用性
                  </Button>
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    disabled={providerArray.fields.length <= 1}
                    onClick={() => providerArray.remove(index)}
                  >
                    删除 Provider
                  </Button>
                </Space>
              </Card>
            ))}

            <Button
              icon={<PlusOutlined />}
              onClick={() => providerArray.append(newProvider(providerArray.fields.length + 1))}
            >
              新增 Provider
            </Button>
          </Space>

          <Divider titlePlacement="start">AI 信息源网站</Divider>
          <Space orientation="vertical" size={12} style={{ width: '100%' }}>
            {sourceArray.fields.map((item, index) => (
              <Card key={item.id} className="glass-card" size="small" variant="borderless">
                <Row gutter={[10, 10]}>
                  <Col xs={24} md={4}>
                    <Form.Item label="来源 ID">
                      <Controller
                        name={`ai_sources.${index}.id`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={5}>
                    <Form.Item label="来源名称">
                      <Controller
                        name={`ai_sources.${index}.name`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={13}>
                    <Form.Item label="URL">
                      <Controller
                        name={`ai_sources.${index}.url`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={2}>
                    <Form.Item label="启用">
                      <Controller
                        name={`ai_sources.${index}.enabled`}
                        control={control}
                        render={({ field }) => (
                          <Switch
                            checked={Boolean(field.value)}
                            onChange={field.onChange}
                            checkedChildren="开"
                            unCheckedChildren="关"
                          />
                        )}
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={sourceArray.fields.length <= 1}
                  onClick={() => sourceArray.remove(index)}
                >
                  删除信息源
                </Button>
              </Card>
            ))}

            <Button
              icon={<PlusOutlined />}
              onClick={() => sourceArray.append(newSource(sourceArray.fields.length + 1))}
            >
              新增信息源
            </Button>
          </Space>

          <Space orientation="vertical" size={6} style={{ marginTop: 14 }}>
            <Typography.Text type="warning">
              每个 Provider 需配置 API 密钥或 Key 路径之一，优先读取 `api_key`。
            </Typography.Text>
            <Typography.Text type="warning">
              当前仍为本地明文存储，请使用最小权限密钥并定期轮换。
            </Typography.Text>
            <Button type="primary" htmlType="submit" loading={saveMutation.isPending}>
              保存配置
            </Button>
          </Space>
        </Form>
      </Card>
    </Space>
  )
}

