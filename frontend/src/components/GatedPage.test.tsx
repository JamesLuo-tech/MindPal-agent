import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GatedPage from './GatedPage'
import { useAuthStore } from '../store/chatStore'

vi.mock('../lib/auth', () => ({
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}))

beforeEach(() => {
  useAuthStore.setState({ authReady: true })
})

describe('GatedPage', () => {
  it('shows a locked prompt over the (still-rendered) content for an anonymous visitor', () => {
    useAuthStore.setState({ user: { id: '1', is_anonymous: true } as any })
    render(
      <GatedPage>
        <p>真实页面内容</p>
      </GatedPage>,
    )

    expect(screen.getByText('登录后解锁')).toBeInTheDocument()
    // 内容仍然渲染在模糊层里，只是被锁定提示盖住
    expect(screen.getByText('真实页面内容')).toBeInTheDocument()
  })

  it('opens the auth form when 去登录 is clicked', async () => {
    const user = userEvent.setup()
    useAuthStore.setState({ user: { id: '1', is_anonymous: true } as any })
    render(
      <GatedPage>
        <p>真实页面内容</p>
      </GatedPage>,
    )

    await user.click(screen.getByText('去登录'))

    expect(screen.getByPlaceholderText('邮箱')).toBeInTheDocument()
  })

  it('renders the page directly for a real account, with no lock overlay', () => {
    useAuthStore.setState({ user: { id: '2', email: 'me@example.com', is_anonymous: false } as any })
    render(
      <GatedPage>
        <p>真实页面内容</p>
      </GatedPage>,
    )

    expect(screen.getByText('真实页面内容')).toBeInTheDocument()
    expect(screen.queryByText('登录后解锁')).not.toBeInTheDocument()
  })
})
