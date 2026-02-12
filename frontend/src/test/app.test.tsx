import { render, screen } from '@testing-library/react'
import { App } from '@/app/App'

describe('App routing', () => {
  it('renders app shell and interactive controls', async () => {
    render(<App />)
    const buttons = await screen.findAllByRole('button')
    expect(buttons.length).toBeGreaterThan(0)
  })
})
