import { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Menu, X, User as UserIcon, LogOut } from 'lucide-react'
import Companion from './Companion'
import AuthPanel from './AuthPanel'
import MascotGridBackdrop from './MascotGridBackdrop'
import { useAuthStore } from '../store/chatStore'
import { signOut } from '../lib/auth'
import { NAV_ITEMS } from '../config/navigation'

/**
 * 窄屏下的顶部条 + 汉堡菜单——网页常见的响应式导航方式，
 * 不用手机 App 那种底部固定 tab 栏 + 悬浮按钮的语言。
 * 菜单里同时装了导航链接和登录入口，桌面端完全隐藏（对应 Sidebar 接管）。
 */
export default function MobileTopBar() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const user = useAuthStore((s) => s.user)
  const isAnonymous = !user || user.is_anonymous
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false)
    }
    if (menuOpen) document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [menuOpen])

  return (
    <>
      <div ref={ref} className="md:hidden sticky top-0 z-20 bg-paper-surface border-b border-paper-sunk">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <Companion mood="idle" size={26} />
            <span className="font-display text-base font-bold text-ink">MindPal</span>
          </div>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? '关闭菜单' : '打开菜单'}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-ink-soft hover:bg-paper-sunk transition-colors"
          >
            {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

        {menuOpen && (
          <nav className="animate-rise-in border-t border-paper-sunk px-4 py-3 space-y-1">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-l-2 border-accent-500 pl-[10px] text-ink bg-paper-sunk'
                      : 'text-ink-soft hover:bg-paper-sunk hover:text-ink'
                  }`
                }
              >
                <Icon className="w-[18px] h-[18px]" strokeWidth={2} />
                {label}
              </NavLink>
            ))}

            <div className="pt-2 mt-2 border-t border-paper-sunk">
              {isAnonymous ? (
                <button
                  onClick={() => {
                    setAuthOpen(true)
                    setMenuOpen(false)
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-ink-soft hover:bg-paper-sunk hover:text-ink transition-colors"
                >
                  <UserIcon className="w-[18px] h-[18px]" strokeWidth={2} />
                  登录
                </button>
              ) : (
                <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl">
                  <div className="w-7 h-7 rounded-full bg-accent-100 text-accent-600 flex items-center justify-center text-xs font-bold shrink-0">
                    {user?.email?.[0]?.toUpperCase() ?? '·'}
                  </div>
                  <span className="text-xs text-ink-soft truncate flex-1">{user?.email}</span>
                  <button
                    onClick={() => signOut()}
                    title="登出"
                    className="text-ink-soft hover:text-red-500 shrink-0"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </nav>
        )}
      </div>

      {authOpen && (
        <div
          className="md:hidden fixed inset-0 z-30 flex items-center justify-center px-4"
          onClick={() => setAuthOpen(false)}
        >
          <MascotGridBackdrop />
          <div onClick={(e) => e.stopPropagation()} className="relative animate-pop-in">
            <button
              onClick={() => setAuthOpen(false)}
              aria-label="关闭"
              className="absolute -top-3 -right-3 w-7 h-7 rounded-full bg-paper-surface shadow-soft flex items-center justify-center text-ink-soft z-10"
            >
              <X className="w-4 h-4" />
            </button>
            <AuthPanel onSuccess={() => setAuthOpen(false)} />
          </div>
        </div>
      )}
    </>
  )
}
