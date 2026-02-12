import { useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
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
import { getConfig, updateConfig } from '@/shared/api/endpoints'
import { PageHeader } from '@/shared/components/PageHeader'
import type { AppConfig } from '@/types/contracts'

const providerSchema = z.object({
  id: z.string().min(1, 'ID必填'),
  label: z.string().min(1, '名称必填'),
  base_url: z.string().url('请输入有效URL'),
  model: z.string().min(1, '模型必填'),
  api_key: z.string(),
  api_key_path: z.string(),
  enabled: z.boolean(),
}).superRefine((value, ctx) => {
  const hasInlineKey = value.api_key.trim().length > 0
  const hasPath = value.api_key_path.trim().length > 0
  if (!hasInlineKey && !hasPath) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: '请至少填写 API 密钥或 API Key 路径',
      path: ['api_key'],
    })
  }
})

const sourceSchema = z.object({
  id: z.string().min(1, 'ID必填'),
  name: z.string().min(1, '名称必填'),
  url: z.string().url('请输入有效URL'),
  enabled: z.boolean(),
})

const schema = z.object({
  tdx_data_path: z.string().min(3),
  markets: z.array(z.enum(['sh', 'sz', 'bj'])).min(1),
  return_window_days: z.number().min(5).max(120),
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
  ai_providers: z.array(providerSchema).min(1, '至少保留一个AI Provider'),
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

export function SettingsPage() {
  const { message } = AntdApp.useApp()
  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  })

  const { control, handleSubmit, reset } = useForm<FormValues>({
    resolver: zodResolver(schema),
  })

  const providerArray = useFieldArray({
    control,
    name: 'ai_providers',
  })

  const sourceArray = useFieldArray({
    control,
    name: 'ai_sources',
  })

  const providers = useWatch({
    control,
    name: 'ai_providers',
  }) ?? []
  const providerOptions = providers.map((provider) => ({
    label: `${provider.label} (${provider.id})`,
    value: provider.id,
  }))

  useEffect(() => {
    if (!configQuery.data) return
    reset(configQuery.data)
  }, [configQuery.data, reset])

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) => updateConfig(values as AppConfig),
    onSuccess: () => message.success('配置已保存'),
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
      message.error('当前激活 Provider 不存在，请重新选择。')
      return
    }
    if (!activeProvider.enabled) {
      message.error('当前激活 Provider 已被禁用，请切换到可用 Provider。')
      return
    }
    if (!hasCredential(activeProvider)) {
      message.error('当前激活 Provider 缺少凭证，请填写 API 密钥或 Key 路径。')
      return
    }

    saveMutation.mutate(values)
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader title="系统设置" subtitle="支持自定义 AI Provider 与信息源，满足多来源接入。" />
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
            <Col xs={24} md={8}>
              <Form.Item label="默认 API 密钥（可选）">
                <Controller
                  name="api_key"
                  control={control}
                  render={({ field }) => (
                    <Input.Password
                      {...field}
                      placeholder="直接填写时优先使用"
                    />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item label="默认 API Key 路径（可选）">
                <Controller
                  name="api_key_path"
                  control={control}
                  render={({ field }) => <Input {...field} />}
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
              <Form.Item label="涨幅窗口">
                <Controller
                  name="return_window_days"
                  control={control}
                  render={({ field }) => (
                    <InputNumber min={5} max={120} value={field.value} onChange={(v) => field.onChange(v ?? 40)} />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="TopN">
                <Controller
                  name="top_n"
                  control={control}
                  render={({ field }) => (
                    <InputNumber min={100} max={2000} step={50} value={field.value} onChange={(v) => field.onChange(v ?? 500)} />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="AI超时(秒)">
                <Controller
                  name="ai_timeout_sec"
                  control={control}
                  render={({ field }) => (
                    <InputNumber min={3} max={60} value={field.value} onChange={(v) => field.onChange(v ?? 10)} />
                  )}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="AI重试次数">
                <Controller
                  name="ai_retry_count"
                  control={control}
                  render={({ field }) => (
                    <InputNumber min={0} max={5} value={field.value} onChange={(v) => field.onChange(v ?? 2)} />
                  )}
                />
              </Form.Item>
            </Col>
          </Row>

          <Divider titlePlacement="start">AI Provider 列表</Divider>
          <Space orientation="vertical" size={12} style={{ width: '100%' }}>
            {providerArray.fields.map((item, index) => (
              <Card key={item.id} className="glass-card" size="small" variant="borderless">
                <Row gutter={[10, 10]}>
                  <Col xs={24} md={4}>
                    <Form.Item label="Provider ID">
                      <Controller
                        name={`ai_providers.${index}.id`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={4}>
                    <Form.Item label="显示名称">
                      <Controller
                        name={`ai_providers.${index}.label`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="Base URL">
                      <Controller
                        name={`ai_providers.${index}.base_url`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={4}>
                    <Form.Item label="默认模型">
                      <Controller
                        name={`ai_providers.${index}.model`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item label="API 密钥（可选）">
                      <Controller
                        name={`ai_providers.${index}.api_key`}
                        control={control}
                        render={({ field }) => (
                          <Input.Password
                            {...field}
                            placeholder="直接填写时优先使用"
                          />
                        )}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={7}>
                    <Form.Item label="API Key 路径（可选）">
                      <Controller
                        name={`ai_providers.${index}.api_key_path`}
                        control={control}
                        render={({ field }) => <Input {...field} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={12} md={1}>
                    <Form.Item label="启用">
                      <Controller
                        name={`ai_providers.${index}.enabled`}
                        control={control}
                        render={({ field }) => (
                          <Switch
                            checked={field.value}
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
                  disabled={providerArray.fields.length <= 1}
                  onClick={() => providerArray.remove(index)}
                >
                  删除 Provider
                </Button>
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
                    <Form.Item label="来源ID">
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
                  <Col xs={12} md={1}>
                    <Form.Item label="启用">
                      <Controller
                        name={`ai_sources.${index}.enabled`}
                        control={control}
                        render={({ field }) => (
                          <Switch
                            checked={field.value}
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
              支持两种凭证方式：直接填 API 密钥 或 配置 Key 路径。读取优先级为
              <Typography.Text strong> api_key &gt; api_key_path </Typography.Text>。
            </Typography.Text>
            <Typography.Text type="warning">
              原型阶段仍为本地明文存储，请使用最小权限 Key 并定期轮换。
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

