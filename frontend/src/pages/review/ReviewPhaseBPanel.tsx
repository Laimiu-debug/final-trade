import { useEffect, useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { App as AntdApp, Alert, Button, Card, Col, Input, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getDailyReviews, getStockCandles, getWeeklyReviews } from '@/shared/api/endpoints'
import { formatPct } from '@/shared/utils/format'
import type { CandlePoint, DailyReviewRecord, WeeklyReviewRecord } from '@/types/contracts'
import { getStockLibraryStats, searchStockLibrary, type StockSearchResult } from '@/shared/services/stockLibrary'

type ReviewPhaseBPanelProps = {
  dateFrom: string
  dateTo: string
}

type PriceSnapshot = {
  latest: number | null
  prev: number | null
  change: number | null
  changePct: number | null
  trend20Pct: number | null
  high20: number | null
  low20: number | null
  sparkline: number[]
}

function tsCodeToPrefixedSymbol(tsCode: string) {
  const [code, suffix] = tsCode.toUpperCase().split('.')
  if (!code || !suffix) return ''
  if (suffix === 'SH') return `sh${code}`
  if (suffix === 'SZ') return `sz${code}`
  if (suffix === 'BJ') return `bj${code}`
  return ''
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function formatPrice(value: number | null) {
  if (value === null || Number.isNaN(value)) return '--'
  return value.toFixed(2)
}

function formatSignedPrice(value: number | null) {
  if (value === null || Number.isNaN(value)) return '--'
  if (value > 0) return `+${value.toFixed(2)}`
  return value.toFixed(2)
}

function formatSignedPct(value: number | null) {
  if (value === null || Number.isNaN(value)) return '--'
  return value > 0 ? `+${(value * 100).toFixed(2)}%` : `${(value * 100).toFixed(2)}%`
}

function pickDailyThought(record: DailyReviewRecord | null) {
  if (!record) return '-'
  return (
    record.reflection.trim()
    || record.summary.trim()
    || record.operations_summary.trim()
    || record.market_summary.trim()
    || '-'
  )
}

function pickWeeklyThought(record: WeeklyReviewRecord | null) {
  if (!record) return '-'
  return (
    record.key_insight.trim()
    || record.next_week_strategy.trim()
    || record.market_rhythm.trim()
    || record.achievements.trim()
    || '-'
  )
}

function shortenText(value: string, max = 72) {
  const text = value.trim()
  if (!text) return '-'
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function calculatePriceSnapshot(candles: CandlePoint[]): PriceSnapshot {
  if (candles.length === 0) {
    return {
      latest: null,
      prev: null,
      change: null,
      changePct: null,
      trend20Pct: null,
      high20: null,
      low20: null,
      sparkline: [],
    }
  }
  const latest = candles[candles.length - 1].close
  const prev = candles.length > 1 ? candles[candles.length - 2].close : null
  const recent20 = candles.slice(-20)
  const trendStart = recent20[0]?.close ?? latest
  const change = prev && prev > 0 ? latest - prev : null
  const changePct = prev && prev > 0 ? (latest - prev) / prev : null
  const trend20Pct = trendStart > 0 ? (latest - trendStart) / trendStart : null
  const high20 = recent20.length > 0 ? Math.max(...recent20.map((item) => item.high)) : null
  const low20 = recent20.length > 0 ? Math.min(...recent20.map((item) => item.low)) : null
  return {
    latest,
    prev,
    change,
    changePct,
    trend20Pct,
    high20,
    low20,
    sparkline: candles.slice(-30).map((item) => item.close),
  }
}

function trendLabel(value: number | null) {
  if (value === null || Number.isNaN(value)) return '未知'
  if (value >= 0.08) return '上升'
  if (value <= -0.08) return '下降'
  return '震荡'
}

function drawSparkline(ctx: CanvasRenderingContext2D, points: number[], x: number, y: number, width: number, height: number) {
  if (points.length < 2) return
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = Math.max(0.0001, max - min)

  ctx.save()
  ctx.beginPath()
  for (let i = 0; i < points.length; i += 1) {
    const px = x + (i / (points.length - 1)) * width
    const py = y + height - ((points[i] - min) / span) * height
    if (i === 0) ctx.moveTo(px, py)
    else ctx.lineTo(px, py)
  }
  ctx.strokeStyle = '#0f766e'
  ctx.lineWidth = 4
  ctx.stroke()
  ctx.restore()
}

function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines: number,
) {
  if (!text.trim()) return
  const chars = Array.from(text)
  const lines: string[] = []
  let current = ''
  for (const char of chars) {
    const next = `${current}${char}`
    if (ctx.measureText(next).width > maxWidth && current) {
      lines.push(current)
      current = char
      if (lines.length >= maxLines) break
    } else {
      current = next
    }
  }
  if (lines.length < maxLines && current) {
    lines.push(current)
  }
  lines.slice(0, maxLines).forEach((line, index) => {
    ctx.fillText(line, x, y + index * lineHeight)
  })
}

export function ReviewPhaseBPanel({ dateFrom, dateTo }: ReviewPhaseBPanelProps) {
  const { message } = AntdApp.useApp()
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<StockSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<StockSearchResult | null>(null)
  const [note, setNote] = useState('')

  const statsQuery = useQuery({
    queryKey: ['stock-library-stats'],
    queryFn: getStockLibraryStats,
  })

  useEffect(() => {
    let active = true
    const timer = window.setTimeout(async () => {
      try {
        if (!keyword.trim()) {
          if (active) {
            setRows([])
            setLoading(false)
          }
          return
        }
        if (active) setLoading(true)
        const result = await searchStockLibrary(keyword.trim(), 30)
        if (active) setRows(result)
      } catch (error) {
        if (active) message.error(error instanceof Error ? error.message : '股票库加载失败')
      } finally {
        if (active) setLoading(false)
      }
    }, 180)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [keyword, message])

  useEffect(() => {
    if (!selected && rows.length > 0) {
      setSelected(rows[0])
    }
  }, [rows, selected])

  const selectedSymbol = useMemo(() => {
    if (!selected) return ''
    return tsCodeToPrefixedSymbol(selected.ts_code).toLowerCase()
  }, [selected])

  const candlesQuery = useQuery({
    queryKey: ['phase-b-share-card-candles', selectedSymbol],
    queryFn: () => getStockCandles(selectedSymbol),
    enabled: Boolean(selectedSymbol),
  })

  const dailyThoughtQuery = useQuery({
    queryKey: ['phase-b-daily-thought', dateFrom, dateTo],
    queryFn: () => getDailyReviews({ date_from: dateFrom, date_to: dateTo }),
  })

  const weeklyThoughtQuery = useQuery({
    queryKey: ['phase-b-weekly-thought', dateFrom, dateTo],
    queryFn: async () => {
      const years = [...new Set([dayjs(dateFrom).year(), dayjs(dateTo).year()])]
      const groups = await Promise.all(years.map((year) => getWeeklyReviews({ year })))
      return groups.flatMap((group) => group.items)
    },
  })

  const priceSnapshot = useMemo(
    () => calculatePriceSnapshot(candlesQuery.data?.candles ?? []),
    [candlesQuery.data?.candles],
  )

  const latestDailyThought = useMemo(() => {
    const items = dailyThoughtQuery.data?.items ?? []
    return (
      items.find(
        (item) => Boolean(item.reflection.trim() || item.summary.trim() || item.operations_summary.trim() || item.market_summary.trim()),
      ) ?? null
    )
  }, [dailyThoughtQuery.data?.items])

  const latestWeeklyThought = useMemo(() => {
    const items = weeklyThoughtQuery.data ?? []
    const sorted = items.slice().sort((a, b) => b.week_label.localeCompare(a.week_label))
    return (
      sorted.find(
        (item) => Boolean(item.key_insight.trim() || item.next_week_strategy.trim() || item.market_rhythm.trim() || item.achievements.trim()),
      ) ?? null
    )
  }, [weeklyThoughtQuery.data])

  const shareText = useMemo(() => {
    if (!selected) return ''
    return [
      `【复盘分享卡】${selected.name} (${selected.ts_code})`,
      `行业: ${selected.industry || '-'}`,
      `市场: ${selected.market || '-'}`,
      `复盘区间: ${dateFrom} ~ ${dateTo}`,
      `最新价: ${formatPrice(priceSnapshot.latest)} (${formatSignedPrice(priceSnapshot.change)} / ${formatSignedPct(priceSnapshot.changePct)})`,
      `20日走势: ${trendLabel(priceSnapshot.trend20Pct)} (${formatSignedPct(priceSnapshot.trend20Pct)})`,
      `20日区间: ${formatPrice(priceSnapshot.low20)} - ${formatPrice(priceSnapshot.high20)}`,
      `日复盘思考${latestDailyThought ? `(${latestDailyThought.date})` : ''}: ${shortenText(pickDailyThought(latestDailyThought), 88)}`,
      `周复盘思考${latestWeeklyThought ? `(${latestWeeklyThought.week_label})` : ''}: ${shortenText(pickWeeklyThought(latestWeeklyThought), 88)}`,
      note.trim() ? `补充观点: ${shortenText(note, 88)}` : '',
    ]
      .filter(Boolean)
      .join('\n')
  }, [dateFrom, dateTo, latestDailyThought, latestWeeklyThought, note, priceSnapshot.change, priceSnapshot.changePct, priceSnapshot.high20, priceSnapshot.latest, priceSnapshot.low20, priceSnapshot.trend20Pct, selected])

  async function handleCopyText() {
    if (!selected) {
      message.warning('请先选择股票')
      return
    }
    try {
      await navigator.clipboard.writeText(shareText)
      message.success('分享文案已复制')
    } catch {
      message.error('复制失败，请手动复制')
    }
  }

  function handleExportShareCard() {
    if (!selected) {
      message.warning('请先选择股票')
      return
    }
    const width = 1080
    const height = 1350
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      message.error('卡片导出失败')
      return
    }

    const gradient = ctx.createLinearGradient(0, 0, width, height)
    gradient.addColorStop(0, '#f5fff8')
    gradient.addColorStop(1, '#e7f6ff')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, width, height)

    ctx.fillStyle = '#0f172a'
    ctx.font = 'bold 52px sans-serif'
    ctx.fillText('Final trade 复盘分享卡', 70, 112)

    ctx.fillStyle = '#1e293b'
    ctx.font = 'bold 70px sans-serif'
    ctx.fillText(selected.name, 70, 220)
    ctx.font = '40px sans-serif'
    ctx.fillText(selected.ts_code, 70, 278)

    ctx.fillStyle = '#334155'
    ctx.font = '34px sans-serif'
    ctx.fillText(`复盘区间: ${dateFrom} ~ ${dateTo}`, 70, 360)
    ctx.fillText(`最新价: ${formatPrice(priceSnapshot.latest)}  (${formatSignedPrice(priceSnapshot.change)} / ${formatSignedPct(priceSnapshot.changePct)})`, 70, 420)
    ctx.fillText(`20日走势: ${trendLabel(priceSnapshot.trend20Pct)} (${formatSignedPct(priceSnapshot.trend20Pct)})`, 70, 476)
    ctx.fillText(`20日区间: ${formatPrice(priceSnapshot.low20)} - ${formatPrice(priceSnapshot.high20)}`, 70, 532)

    ctx.strokeStyle = '#94a3b8'
    ctx.lineWidth = 2
    ctx.strokeRect(70, 575, 940, 200)
    drawSparkline(ctx, priceSnapshot.sparkline, 98, 610, 885, 130)

    ctx.fillStyle = '#0f172a'
    ctx.font = 'bold 34px sans-serif'
    ctx.fillText(`日复盘思考${latestDailyThought ? ` (${latestDailyThought.date})` : ''}`, 70, 858)
    ctx.font = '30px sans-serif'
    drawWrappedText(ctx, pickDailyThought(latestDailyThought), 70, 902, 940, 42, 2)

    ctx.fillStyle = '#0f172a'
    ctx.font = 'bold 34px sans-serif'
    ctx.fillText(`周复盘思考${latestWeeklyThought ? ` (${latestWeeklyThought.week_label})` : ''}`, 70, 1014)
    ctx.font = '30px sans-serif'
    drawWrappedText(ctx, pickWeeklyThought(latestWeeklyThought), 70, 1058, 940, 42, 2)

    if (note.trim()) {
      ctx.fillStyle = '#0f172a'
      ctx.font = 'bold 32px sans-serif'
      ctx.fillText('补充观点', 70, 1170)
      ctx.font = '28px sans-serif'
      drawWrappedText(ctx, note.trim(), 70, 1208, 940, 38, 2)
    }

    ctx.fillStyle = '#475569'
    ctx.font = '26px sans-serif'
    ctx.fillText(`生成时间: ${new Date().toLocaleString()}`, 70, 1280)

    canvas.toBlob((blob) => {
      if (!blob) {
        message.error('卡片导出失败')
        return
      }
      downloadBlob(`share-card-${selected.symbol}-${Date.now()}.png`, blob)
      message.success('分享卡片已导出')
    }, 'image/png')
  }

  const columns: ColumnsType<StockSearchResult> = [
    { title: '代码', dataIndex: 'ts_code', width: 120 },
    { title: '简称', dataIndex: 'name', width: 140 },
    { title: '行业', dataIndex: 'industry', width: 130 },
    { title: '市场', dataIndex: 'market', width: 100 },
    {
      title: '匹配',
      dataIndex: 'matchType',
      width: 90,
      render: (value: StockSearchResult['matchType']) => (
        <Tag color={value === 'code' ? 'blue' : value === 'name' ? 'green' : 'purple'}>{value}</Tag>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Typography.Text strong>股票搜索库</Typography.Text>
          <Typography.Text type="secondary">
            支持代码 / 名称 / 拼音检索，数据量 {statsQuery.data?.total ?? '-'} 条
          </Typography.Text>
          <Input
            allowClear
            placeholder="输入代码、名称或拼音（例如：600519 / 贵州茅台 / gzm）"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <Table
            rowKey={(row) => row.ts_code}
            loading={loading}
            columns={columns}
            dataSource={rows}
            size="small"
            pagination={{ pageSize: 8, showSizeChanger: false }}
            rowSelection={{
              type: 'radio',
              selectedRowKeys: selected ? [selected.ts_code] : [],
              onChange: (keys) => {
                const key = String(keys[0] || '')
                const row = rows.find((item) => item.ts_code === key) || null
                setSelected(row)
              },
            }}
            onRow={(record) => ({
              onClick: () => setSelected(record),
            })}
          />
        </Space>
      </Card>

      {candlesQuery.error ? (
        <Alert
          type="warning"
          showIcon
          message="行情加载失败"
          description="当前无法获取该股票价格走势，分享卡片将展示可用复盘内容。"
        />
      ) : null}

      <Card size="small" title="分享卡片预览">
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={14}>
            <Card
              style={{
                borderRadius: 14,
                background: 'linear-gradient(135deg, rgba(241,255,247,0.9), rgba(232,245,255,0.9))',
              }}
            >
              <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                <Typography.Text type="secondary">Final trade</Typography.Text>
                <Typography.Title level={3} style={{ margin: 0 }}>
                  {selected?.name || '请选择一只股票'}
                </Typography.Title>
                <Typography.Text>{selected?.ts_code || '-'}</Typography.Text>
                <Typography.Text>行业: {selected?.industry || '-'}</Typography.Text>
                <Typography.Text>市场: {selected?.market || '-'}</Typography.Text>
                <Typography.Text>复盘区间: {dateFrom} ~ {dateTo}</Typography.Text>
                <Typography.Text>
                  最新价: {formatPrice(priceSnapshot.latest)} ({formatSignedPrice(priceSnapshot.change)} / {formatSignedPct(priceSnapshot.changePct)})
                </Typography.Text>
                <Typography.Text>
                  20日走势: {trendLabel(priceSnapshot.trend20Pct)} ({formatPct(priceSnapshot.trend20Pct ?? 0)})
                </Typography.Text>
                <Typography.Text>
                  20日区间: {formatPrice(priceSnapshot.low20)} - {formatPrice(priceSnapshot.high20)}
                </Typography.Text>
                <Typography.Text>
                  日复盘思考{latestDailyThought ? ` (${latestDailyThought.date})` : ''}: {shortenText(pickDailyThought(latestDailyThought))}
                </Typography.Text>
                <Typography.Text>
                  周复盘思考{latestWeeklyThought ? ` (${latestWeeklyThought.week_label})` : ''}: {shortenText(pickWeeklyThought(latestWeeklyThought))}
                </Typography.Text>
                {candlesQuery.isLoading ? <Typography.Text type="secondary">正在加载走势数据...</Typography.Text> : null}
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Input.TextArea
                rows={6}
                placeholder="可选补充观点，导出卡片时会带上"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <Space>
                <Button type="primary" onClick={handleExportShareCard} disabled={!selected}>
                  导出分享卡片 PNG
                </Button>
                <Button onClick={handleCopyText} disabled={!selected}>
                  复制分享文案
                </Button>
              </Space>
              <Input.TextArea value={shareText} rows={10} readOnly />
            </Space>
          </Col>
        </Row>
      </Card>
    </Space>
  )
}
