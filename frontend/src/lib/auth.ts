import { supabase } from './supabase'

/**
 * 纯函数形式的登录/注册/登出——不依赖 hook 状态，任何组件（侧边栏角落的登录卡片、
 * 移动端登录按钮……）都能直接调用，不用担心重复挂载 useAuthBootstrap 的副作用。
 */
export const signIn = (email: string, password: string) =>
  supabase.auth.signInWithPassword({ email, password })

export const signUp = (email: string, password: string) =>
  supabase.auth.signUp({ email, password })

export async function signOut() {
  await supabase.auth.signOut()
  // 登出后立刻重新匿名登录，保证"聊聊"不间断可用
  await supabase.auth.signInAnonymously()
}
