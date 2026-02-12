import { render, screen } from '@testing-library/react'
import { App } from '@/app/App'

describe('App routing', () => {
  it('renders screener entry page', async () => {
    render(<App />)
    expect(await screen.findByText('选股漏斗控制台')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '运行第1步' })).toBeInTheDocument()
  })
})
