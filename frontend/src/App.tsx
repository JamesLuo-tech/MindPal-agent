import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthBootstrap } from './hooks/useAuth'
import { useAuthStore } from './store/chatStore'
import AppShell from './layouts/AppShell'
import Chat from './pages/Chat'
import Today from './pages/Today'
import SmallSteps from './pages/SmallSteps'
import Changes from './pages/Changes'
import Support from './pages/Support'
import GatedPage from './components/GatedPage'
import Companion from './components/Companion'

/** 首次会话解析（含静默匿名登录）完成前显示一个轻量的品牌启动态，避免"未登录锁定"闪一下 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const authReady = useAuthStore((s) => s.authReady)
  if (!authReady) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-paper">
        <Companion mood="idle" size={64} />
        <p className="font-display text-sm text-ink-soft">MindPal 正在准备…</p>
      </div>
    )
  }
  return <>{children}</>
}

export default function App() {
  useAuthBootstrap()

  return (
    <AuthGate>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/chat" replace />} />
            {/* 聊聊对匿名访客也完全开放 */}
            <Route path="/chat" element={<Chat />} />
            {/* 其余 4 个 tab 需要真实账号，匿名访客看到的是模糊预览 + 登录提示 */}
            <Route path="/today" element={<GatedPage><Today /></GatedPage>} />
            <Route path="/steps" element={<GatedPage><SmallSteps /></GatedPage>} />
            <Route path="/changes" element={<GatedPage><Changes /></GatedPage>} />
            <Route path="/support" element={<GatedPage><Support /></GatedPage>} />
          </Route>

          {/* 旧链接兼容重定向：登录不再是独立页面，改成侧边栏角落的登录卡片 */}
          <Route path="/login" element={<Navigate to="/chat" replace />} />
          <Route path="/emotions" element={<Navigate to="/changes" replace />} />
          <Route path="/report" element={<Navigate to="/changes?view=trend" replace />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthGate>
  )
}
