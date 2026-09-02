import { useState } from 'react'
import { Lock } from 'lucide-react'
import { useAuthStore } from '../store/chatStore'
import AuthPanel from './AuthPanel'

/**
 * 包住"今日/小步行动/变化/支持"这几个需要账号的页面：
 * 匿名访客能看到页面大致长什么样（内容照常渲染，只是模糊+压暗），
 * 中间叠一张"登录后解锁"提示卡——既说清楚为什么看不了，也把这几页的设计露出来。
 */
export default function GatedPage({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)
  const isAnonymous = !user || user.is_anonymous

  if (!isAnonymous) return <>{children}</>

  return (
    <div className="relative flex-1 min-h-0 overflow-hidden flex flex-col">
      <div className="flex-1 min-h-0 overflow-hidden pointer-events-none select-none blur-[3px] opacity-60 flex flex-col">
        {children}
      </div>
      <div className="absolute inset-0 flex items-center justify-center bg-paper/50 px-6">
        <div className="bg-paper-surface rounded-2xl shadow-ambient p-6 max-w-xs w-full text-center">
          {!open && (
            <>
              <div className="w-11 h-11 rounded-full bg-accent-50 text-accent-500 flex items-center justify-center mx-auto mb-3">
                <Lock className="w-5 h-5" strokeWidth={2} />
              </div>
              <p className="font-display text-base font-bold text-ink mb-1">登录后解锁</p>
              <p className="text-xs text-ink-soft mb-4 leading-relaxed">
                这里需要一个账号，才能长期保存你的记录
              </p>
              <button
                onClick={() => setOpen(true)}
                className="w-full py-2.5 rounded-xl bg-accent-500 text-white text-sm font-medium hover:bg-accent-600 active:scale-[0.98] transition"
              >
                去登录
              </button>
            </>
          )}
          {open && <AuthPanel variant="bare" onSuccess={() => setOpen(false)} />}
        </div>
      </div>
    </div>
  )
}
