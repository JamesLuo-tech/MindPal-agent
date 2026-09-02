import { useEffect, useRef, useState } from 'react'
import { User as UserIcon, LogOut } from 'lucide-react'
import { useAuthStore } from '../store/chatStore'
import { signOut } from '../lib/auth'
import AuthPanel from './AuthPanel'
import MascotGridBackdrop from './MascotGridBackdrop'

/** 侧边栏左下角的登录入口——不再是独立的登录页，点开是悬浮在上方的小卡片 */
export default function LoginWidget() {
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const isAnonymous = !user || user.is_anonymous

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  return (
    <div ref={ref} className="relative mt-auto pt-4">
      {open && (
        <div className="absolute bottom-full left-0 mb-2 z-30 animate-pop-in w-80 rounded-2xl overflow-hidden shadow-ambient">
          <MascotGridBackdrop />
          <div className="relative flex items-center justify-center p-6 min-h-[420px]">
            <AuthPanel onSuccess={() => setOpen(false)} />
          </div>
        </div>
      )}

      {isAnonymous ? (
        <button
          onClick={() => setOpen((v) => !v)}
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
  )
}
