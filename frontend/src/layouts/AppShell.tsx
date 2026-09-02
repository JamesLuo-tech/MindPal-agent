import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import MobileTopBar from '../components/MobileTopBar'

/**
 * 5 个 tab 共用的应用外壳：桌面端左侧固定侧边栏 + 右侧全宽内容区（网站布局）。
 * 窄屏下用顶部条 + 汉堡菜单（网页常见的响应式导航），不用手机 App 那种
 * 底部固定 tab 栏 + 悬浮按钮的语言。每个 tab 页面自己负责页头和内容排版。
 */
export default function AppShell() {
  const location = useLocation()

  return (
    <div className="min-h-screen flex bg-paper">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-50 focus:top-4 focus:left-4 focus:px-4 focus:py-2 focus:rounded-xl focus:bg-accent-500 focus:text-white focus:text-sm"
      >
        跳到主要内容
      </a>

      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <MobileTopBar />
        <main id="main-content" className="flex-1 flex flex-col min-h-0">
          {/* key 用路径驱动，切 tab 时内容重新播放一次入场动效 */}
          <div key={location.pathname} className="flex-1 flex flex-col min-h-0 animate-page-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
