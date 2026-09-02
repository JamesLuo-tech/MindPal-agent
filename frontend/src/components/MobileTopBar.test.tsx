import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import MobileTopBar from './MobileTopBar'
import { useAuthStore } from '../store/chatStore'
import * as auth from '../lib/auth'

vi.mock('../lib/auth', () => ({
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}))

function renderBar() {
  return render(
    <MemoryRouter initialEntries={['/today']}>
      <MobileTopBar />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useAuthStore.setState({ user: { id: '1', is_anonymous: true } as any, authReady: true })
})

describe('MobileTopBar', () => {
  it('shows the brand mark and keeps the menu closed by default', () => {
    renderBar()
    expect(screen.getByText('MindPal')).toBeInTheDocument()
    expect(screen.queryByText('聊聊')).not.toBeInTheDocument()
  })

  it('opens the nav menu when the hamburger button is clicked', async () => {
    const user = userEvent.setup()
    renderBar()

    await user.click(screen.getByLabelText('打开菜单'))

    for (const label of ['今日', '聊聊', '小步行动', '变化', '支持']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('closes the menu after a nav link is clicked', async () => {
    const user = userEvent.setup()
    renderBar()
    await user.click(screen.getByLabelText('打开菜单'))

    await user.click(screen.getByText('聊聊'))

    expect(screen.queryByText('聊聊')).not.toBeInTheDocument()
  })

  it('opens the login modal from the menu for an anonymous visitor', async () => {
    const user = userEvent.setup()
    renderBar()
    await user.click(screen.getByLabelText('打开菜单'))

    await user.click(screen.getByText('登录'))

    expect(screen.getByPlaceholderText('邮箱')).toBeInTheDocument()
    // 打开登录弹窗的同时菜单应该收起
    expect(screen.queryByText('今日')).not.toBeInTheDocument()
  })

  it('shows the account email and signs out for a real session', async () => {
    useAuthStore.setState({ user: { id: '2', email: 'me@example.com', is_anonymous: false } as any })
    const user = userEvent.setup()
    renderBar()
    await user.click(screen.getByLabelText('打开菜单'))

    expect(screen.getByText('me@example.com')).toBeInTheDocument()
    await user.click(screen.getByTitle('登出'))
    expect(auth.signOut).toHaveBeenCalled()
  })
})
