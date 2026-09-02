import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Sidebar from './Sidebar'

const LABELS = ['今日', '聊聊', '小步行动', '变化', '支持']

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
    </MemoryRouter>,
  )
}

describe('Sidebar', () => {
  it('renders the brand mark and all 5 nav items', () => {
    renderAt('/today')
    expect(screen.getByText('MindPal')).toBeInTheDocument()
    for (const label of LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('highlights the item matching the current route', () => {
    renderAt('/support')
    expect(screen.getByText('支持').closest('a')).toHaveClass('border-accent-500')
    expect(screen.getByText('今日').closest('a')).not.toHaveClass('border-accent-500')
  })

  it('links each item to its route', () => {
    renderAt('/today')
    expect(screen.getByText('今日').closest('a')).toHaveAttribute('href', '/today')
    expect(screen.getByText('聊聊').closest('a')).toHaveAttribute('href', '/chat')
    expect(screen.getByText('小步行动').closest('a')).toHaveAttribute('href', '/steps')
    expect(screen.getByText('变化').closest('a')).toHaveAttribute('href', '/changes')
    expect(screen.getByText('支持').closest('a')).toHaveAttribute('href', '/support')
  })
})
