import { useState } from 'react'
import Companion, { type CompanionMood } from './Companion'
import { signIn, signUp } from '../lib/auth'

interface Props {
  onSuccess?: () => void
  /** 'card' 自带背景/阴影/圆角（用于弹出气泡、独立弹窗）；'bare' 只有表单本身（用于嵌进已有卡片里） */
  variant?: 'card' | 'bare'
}

/** 登录/注册表单本体——从原来的独立登录页搬过来，现在被嵌进侧边栏角落的弹出卡片、
 * 移动端弹窗、锁定页提示卡片这三处复用，不再是一整个路由页面。 */
export default function AuthPanel({ onSuccess, variant = 'card' }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [mood, setMood] = useState<CompanionMood>('idle')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    setMood('thinking')
    try {
      const { error: err } =
        mode === 'login' ? await signIn(email, password) : await signUp(email, password)
      if (err) throw err
      setMood('happy')
      onSuccess?.()
    } catch (e: any) {
      setError(e.message ?? '操作失败，请重试')
      setMood('idle')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={variant === 'card' ? 'w-72 bg-paper-surface rounded-2xl shadow-ambient p-5' : ''}>
      <div className="flex items-center gap-2.5 mb-4">
        <Companion mood={mood} size={28} />
        <div>
          <p className="font-display text-sm font-bold text-ink leading-tight">登录 MindPal</p>
          <p className="text-[11px] text-ink-soft mt-0.5">解锁今日 / 小步行动 / 变化 / 支持</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-2.5">
        <input
          type="email"
          placeholder="邮箱"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="w-full px-3.5 py-2.5 bg-paper-sunk rounded-xl text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 transition-shadow"
        />
        <input
          type="password"
          placeholder="密码"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="w-full px-3.5 py-2.5 bg-paper-sunk rounded-xl text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 transition-shadow"
        />
        {error && <p className="text-red-500 text-xs px-1">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 mt-1 bg-accent-500 text-white rounded-xl text-sm font-display font-semibold tracking-wide hover:bg-accent-600 active:scale-[0.98] transition disabled:opacity-50"
        >
          {loading ? '处理中…' : mode === 'login' ? '登录' : '注册'}
        </button>
      </form>

      <button
        onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
        className="mt-3 text-xs text-ink-soft hover:text-ink w-full text-center transition-colors"
      >
        {mode === 'login' ? '还没有账号？注册' : '已有账号？登录'}
      </button>
    </div>
  )
}
