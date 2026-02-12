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

const navItems: ItemType[] = [
  { key: '/screener', icon: <FilterIcon />, label: '选股漏斗' },
  { key: '/signals', icon: <AimOutlined />, label: '待买信号' },
  { key: '/trade', icon: <SwapOutlined />, label: '模拟交易' },
  { key: '/portfolio', icon: <LineChartOutlined />, label: '持仓管理' },
  { key: '/review', icon: <BarChartOutlined />, label: '复盘统计' },
  { key: '/ai', icon: <RadarChartOutlined />, label: 'AI分析' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

function FilterIcon() {
  return <FundProjectionScreenOutlined />
}

function resolveSelected(pathname: string) {
  if (pathname.startsWith('/stocks/')) return '/screener'
  return pathname
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
          navigate(key)
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
              TDX Trend
            </Typography.Title>
            <Typography.Text type="secondary">前端原型版</Typography.Text>
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
              <a
                onClick={() => setDrawerOpen(true)}
                style={{ cursor: 'pointer', color: '#0a6b54' }}
              >
                导航
              </a>
            ) : null}
            <Typography.Text strong>通达信趋势选股系统</Typography.Text>
          </Space>

          <Space size={18}>
            <Link to="/screener">主流程</Link>
            <Link to="/settings">配置</Link>
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

