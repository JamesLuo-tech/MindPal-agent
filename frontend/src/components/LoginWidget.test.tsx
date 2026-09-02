import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LoginWidget from './LoginWidget'
import { useAuthStore } from '../store/chatStore'
import * as auth from '../lib/auth'

vi.mock('../lib/auth', () => ({
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}))

beforeEach(() => {
  useAuthStore.setState({ user: null, authReady: true })
})

describe('LoginWidget', () => {
  it('shows a 登录 button for an anonymous/no-session visitor', () => {
    useAuthStore.setState({ user: { id: '1', is_anonymous: true } as any })
    render(<LoginWidget />)
    expect(screen.getByText('登录')).toBeInTheDocument()
  })

  it('opens the auth panel when the 登录 button is clicked', async () => {
    const user = userEvent.setup()
    useAuthStore.setState({ user: { id: '1', is_anonymous: true } as any })
    render(<LoginWidget />)

    await user.click(screen.getByText('登录'))

    expect(screen.getByPlaceholderText('邮箱')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('密码')).toBeInTheDocument()
  })

  it('shows the account email and a logout control for a real session', () => {
    useAuthStore.setState({ user: { id: '2', email: 'me@example.com', is_anonymous: false } as any })
    render(<LoginWidget />)

    expect(screen.getByText('me@example.com')).toBeInTheDocument()
    expect(screen.queryByText('登录')).not.toBeInTheDocument()
  })

  it('calls signOut when the logout control is clicked', async () => {
    const user = userEvent.setup()
    useAuthStore.setState({ user: { id: '2', email: 'me@example.com', is_anonymous: false } as any })
    render(<LoginWidget />)

    await user.click(screen.getByTitle('登出'))

    expect(auth.signOut).toHaveBeenCalled()
  })
})
