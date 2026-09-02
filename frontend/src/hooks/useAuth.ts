import { useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { useAuthStore } from '../store/chatStore'

/**
 * 只应该在 App 顶层挂载一次：解析已有会话，没有会话就静默匿名登录，
 * 让"聊聊"不用注册/登录也能立刻用。其余组件读 useAuthStore 就够了，
 * 不要再到处调用这个 hook——不然会话引导逻辑会跟着每个挂载点重复跑。
 */
export function useAuthBootstrap() {
  const setUser = useAuthStore((s) => s.setUser)
  const setAuthReady = useAuthStore((s) => s.setAuthReady)

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      const { data } = await supabase.auth.getSession()
      if (data.session) {
        if (!cancelled) setUser(data.session.user)
      } else {
        const { data: anonData, error } = await supabase.auth.signInAnonymously()
        if (!cancelled && !error) setUser(anonData.user)
      }
      if (!cancelled) setAuthReady(true)
    }
    bootstrap()

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null)
    })
    return () => {
      cancelled = true
      subscription.unsubscribe()
    }
  }, [setUser, setAuthReady])
}
