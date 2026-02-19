import { useMemo, useState } from 'react'
import {
  AimOutlined,
  AreaChartOutlined,
  BarChartOutlined,
  FundProjectionScreenOutlined,
  LineChartOutlined,
  RadarChartOutlined,
  SettingOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { Drawer, Grid, Layout, Menu, Space, Typography } from 'antd'
import type { ItemType } from 'antd/es/menu/interface'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

const { Header, Content, Sider } = Layout
const SCREENER_CACHE_KEY = 'tdx-trend-screener-cache-v4'

const navItems: ItemType[] = [
  { key: '/screener', icon: <FilterIcon />, label: '选股漏斗' },
  { key: '/signals', icon: <AimOutlined />, label: '待买信号' },
  { key: '/trade', icon: <SwapOutlined />, label: '模拟交易' },
  { key: '/portfolio', icon: <LineChartOutlined />, label: '持仓管理' },
  { key: '/review', icon: <BarChartOutlined />, label: '复盘统计' },
  { key: '/review/share', icon: <AreaChartOutlined />, label: '股票搜索与分享' },
  { key: '/review/news', icon: <BarChartOutlined />, label: '资讯面板' },
  { key: '/ai', icon: <RadarChartOutlined />, label: 'AI分析' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

function FilterIcon() {
  return <FundProjectionScreenOutlined />
}

function resolveSelected(pathname: string) {
  if (pathname.startsWith('/stocks/')) return '/screener'
  if (pathname.startsWith('/review/share')) return '/review/share'
  if (pathname.startsWith('/review/news')) return '/review/news'
  return pathname
}

function buildSignalsRouteFromScreenerCache(): string {
  try {
    const raw = window.localStorage.getItem(SCREENER_CACHE_KEY)
    if (!raw) return '/signals'
    const parsed = JSON.parse(raw) as { run_meta?: { runId?: unknown; asOfDate?: unknown } }
    const runId = typeof parsed?.run_meta?.runId === 'string' ? parsed.run_meta.runId.trim() : ''
    const asOfDate = typeof parsed?.run_meta?.asOfDate === 'string' ? parsed.run_meta.asOfDate.trim() : ''
    if (!runId) return '/signals'
    const params = new URLSearchParams({
      mode: 'trend_pool',
      run_id: runId,
      trend_step: 'auto',
    })
    if (asOfDate) params.set('as_of_date', asOfDate)
    return `/signals?${params.toString()}`
  } catch {
    return '/signals'
  }
}

export function AppShell() {
  const screens = Grid.useBreakpoint()
  const location = useLocation()
  const navigate = useNavigate()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const selectedKey = resolveSelected(location.pathname)
  const isMobile = !screens.lg

  const menu = useMemo(
    () => (
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        items={navItems}
        onClick={({ key }) => {
          const target = key === '/signals' ? buildSignalsRouteFromScreenerCache() : key
          navigate(target)
          setDrawerOpen(false)
        }}
        style={{ border: 'none', background: 'transparent' }}
      />
    ),
    [navigate, selectedKey],
  )

  return (
    <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
      {isMobile ? (
        <Drawer
          title="导航"
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          styles={{ body: { padding: 10 } }}
        >
          {menu}
        </Drawer>
      ) : (
        <Sider
          width={248}
          style={{
            background: 'rgba(251, 255, 252, 0.68)',
            borderRight: '1px solid rgba(31,49,48,0.08)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <div style={{ padding: '20px 16px 12px' }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              Final trade
            </Typography.Title>
            <Typography.Text type="secondary">Final trade</Typography.Text>
          </div>
          {menu}
        </Sider>
      )}

      <Layout style={{ background: 'transparent' }}>
        <Header
          style={{
            background: 'transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid rgba(31,49,48,0.08)',
            paddingInline: 16,
          }}
        >
          <Space size={12}>
            {isMobile ? (
              <a onClick={() => setDrawerOpen(true)} style={{ cursor: 'pointer', color: '#0a6b54' }}>
                导航
              </a>
            ) : null}
            <Typography.Text strong>Final trade</Typography.Text>
          </Space>

          <Space size={18}>
            <Link to="/screener">主流程</Link>
            <Link to="/settings">设置</Link>
            <AreaChartOutlined style={{ color: '#0f8b6f' }} />
          </Space>
        </Header>

        <Content style={{ padding: '18px 18px 24px' }}>
          <div className="float-in">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
