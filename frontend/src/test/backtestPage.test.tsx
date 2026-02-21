import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/mocks/server'
import { BacktestPage } from '@/pages/backtest/BacktestPage'
import { BacktestTaskWatcher } from '@/shared/components/BacktestTaskWatcher'
import { useBacktestTaskStore } from '@/state/backtestTaskStore'
import { renderWithProviders } from '@/test/renderWithProviders'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echart" />,
}))

describe('BacktestPage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useBacktestTaskStore.setState({
      tasksById: {},
      activeTaskIds: [],
      selectedTaskId: undefined,
    })
  })

  it('runs backtest and renders result summary', async () => {
    let pollCount = 0
    server.use(
      http.post('/api/backtest/tasks', async () => {
        await delay(20)
        return HttpResponse.json({ task_id: 'bt_test_001' })
      }),
      http.get('/api/backtest/tasks/:taskId', async () => {
        pollCount += 1
        await delay(20)
        if (pollCount <= 1) {
          return HttpResponse.json({
            task_id: 'bt_test_001',
            status: 'running',
            progress: {
              mode: 'daily',
              current_date: '2026-01-10',
              processed_dates: 1,
              total_dates: 3,
              percent: 33.3,
              message: '滚动筛选进度 1/3',
              started_at: '2026-02-20 10:00:00',
              updated_at: '2026-02-20 10:00:01',
            },
          })
        }
        await delay(20)
        return HttpResponse.json({
          task_id: 'bt_test_001',
          status: 'succeeded',
          progress: {
            mode: 'daily',
            current_date: '2026-01-31',
            processed_dates: 3,
            total_dates: 3,
            percent: 100,
            message: '回测完成。',
            started_at: '2026-02-20 10:00:00',
            updated_at: '2026-02-20 10:00:05',
          },
          result: {
          stats: {
            win_rate: 0.5,
            total_return: 0.08,
            max_drawdown: 0.05,
            avg_pnl_ratio: 0.02,
            trade_count: 2,
            win_count: 1,
            loss_count: 1,
            profit_factor: 1.4,
          },
          trades: [
            {
              symbol: 'sz300750',
              name: '宁德时代',
              signal_date: '2026-01-02',
              entry_date: '2026-01-03',
              exit_date: '2026-01-10',
              entry_signal: 'SOS',
              entry_phase: '吸筹D',
              entry_quality_score: 78.5,
              exit_reason: 'event_exit',
              quantity: 100,
              entry_price: 160,
              exit_price: 170,
              holding_days: 7,
              pnl_amount: 980,
              pnl_ratio: 0.06125,
            },
          ],
          equity_curve: [
            { date: '2026-01-01', equity: 1_000_000, realized_pnl: 0 },
            { date: '2026-01-10', equity: 1_000_980, realized_pnl: 980 },
          ],
          drawdown_curve: [
            { date: '2026-01-01', drawdown: 0 },
            { date: '2026-01-10', drawdown: -0.01 },
          ],
          monthly_returns: [
            { month: '2026-01', return_ratio: 0.00098, pnl_amount: 980, trade_count: 1 },
          ],
          top_trades: [],
          bottom_trades: [],
          cost_snapshot: {
            initial_capital: 1_000_000,
            commission_rate: 0.0008,
            min_commission: 0,
            stamp_tax_rate: 0,
            transfer_fee_rate: 0,
            slippage_rate: 0,
          },
          range: {
            date_from: '2026-01-01',
            date_to: '2026-01-31',
            date_axis: 'sell',
          },
          notes: ['mock note'],
          candidate_count: 6,
          skipped_count: 2,
          fill_rate: 0.333333,
          max_concurrent_positions: 2,
          },
        })
      }),
    )

    renderWithProviders(
      <>
        <BacktestTaskWatcher />
        <BacktestPage />
      </>,
      '/backtest',
    )
    const runButton = await screen.findByRole('button', { name: '开始回测' })
    await userEvent.click(runButton)

    expect(await screen.findByText('候选信号')).toBeInTheDocument()
    expect(await screen.findByText('sz300750')).toBeInTheDocument()
    const chartLink = await screen.findByRole('link', { name: 'sz300750' })
    expect(chartLink.getAttribute('href')).toContain('/stocks/sz300750/chart')
    expect(await screen.findByText('mock note')).toBeInTheDocument()
  }, 12_000)

  it('binds latest screener run_id into backtest form', async () => {
    server.use(
      http.get('/api/screener/latest-run', async () => {
        await delay(20)
        return HttpResponse.json({
          run_id: 'latest-run-20260220',
          created_at: '2026-02-20 09:30:00',
          as_of_date: '2026-02-19',
          params: {
            markets: ['sh', 'sz'],
            mode: 'strict',
            return_window_days: 40,
            top_n: 500,
            turnover_threshold: 0.05,
            amount_threshold: 500000000,
            amplitude_threshold: 0.03,
          },
          step_summary: {
            input_count: 5100,
            step1_count: 400,
            step2_count: 68,
            step3_count: 26,
            step4_count: 5,
            final_count: 0,
          },
          step_pools: {
            input: [],
            step1: [],
            step2: [],
            step3: [],
            step4: [],
            final: [],
          },
          results: [],
          degraded: false,
        })
      }),
    )

    renderWithProviders(
      <>
        <BacktestTaskWatcher />
        <BacktestPage />
      </>,
      '/backtest',
    )
    const bindButton = await screen.findByRole('button', { name: '带入最新筛选' })
    await userEvent.click(bindButton)

    expect(await screen.findByDisplayValue('latest-run-20260220')).toBeInTheDocument()
  })

  it('submits full_market via task api instead of sync api', async () => {
    let syncRunCalled = false
    server.use(
      http.post('/api/backtest/run', async () => {
        syncRunCalled = true
        return HttpResponse.json({ error: 'should not be called' }, { status: 500 })
      }),
      http.post('/api/backtest/tasks', async () => {
        await delay(20)
        return HttpResponse.json({ task_id: 'bt_test_full_001' })
      }),
      http.get('/api/backtest/tasks/:taskId', async () => {
        await delay(20)
        return HttpResponse.json({
          task_id: 'bt_test_full_001',
          status: 'succeeded',
          progress: {
            mode: 'weekly',
            current_date: '2026-01-31',
            processed_dates: 2,
            total_dates: 2,
            percent: 100,
            message: '回测完成。',
            started_at: '2026-02-20 10:00:00',
            updated_at: '2026-02-20 10:00:05',
          },
          result: {
            stats: {
              win_rate: 0.5,
              total_return: 0.08,
              max_drawdown: 0.05,
              avg_pnl_ratio: 0.02,
              trade_count: 2,
              win_count: 1,
              loss_count: 1,
              profit_factor: 1.4,
            },
            trades: [],
            equity_curve: [],
            drawdown_curve: [],
            monthly_returns: [],
            top_trades: [],
            bottom_trades: [],
            cost_snapshot: {
              initial_capital: 1_000_000,
              commission_rate: 0.0008,
              min_commission: 0,
              stamp_tax_rate: 0,
              transfer_fee_rate: 0,
              slippage_rate: 0,
            },
            range: {
              date_from: '2026-01-01',
              date_to: '2026-01-31',
              date_axis: 'sell',
            },
            notes: ['full market task'],
            candidate_count: 0,
            skipped_count: 0,
            fill_rate: 0,
            max_concurrent_positions: 0,
          },
        })
      }),
    )

    renderWithProviders(
      <>
        <BacktestTaskWatcher />
        <BacktestPage />
      </>,
      '/backtest',
    )
    await userEvent.click(await screen.findByText('全市场'))
    await userEvent.click(await screen.findByRole('button', { name: '开始回测' }))

    expect(await screen.findByText('full market task')).toBeInTheDocument()
    expect(syncRunCalled).toBe(false)
  }, 12_000)
})
