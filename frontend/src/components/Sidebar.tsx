import { NavLink } from 'react-router-dom'
import Companion from './Companion'
import LoginWidget from './LoginWidget'
import { NAV_ITEMS } from '../config/navigation'

/** 桌面端左侧导航栏；移动端隐藏，改用 MobileTopBar 的顶部条 + 汉堡菜单 */
export default function Sidebar() {
  return (
    <aside className="hidden md:flex w-60 shrink-0 flex-col bg-paper-surface border-r border-paper-sunk px-4 py-6">
      <div className="flex items-center gap-2.5 px-2 mb-8">
        <Companion mood="idle" size={34} />
        <span className="font-display text-lg font-bold text-ink">MindPal</span>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `group flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                isActive
                  ? 'border-l-2 border-accent-500 pl-[10px] text-ink bg-paper-sunk'
                  : 'text-ink-soft hover:bg-paper-sunk hover:text-ink'
              }`
            }
          >
            <Icon className="w-[18px] h-[18px] transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* 登录入口：页面左下角的小卡片，不再是独立登录页 */}
      <LoginWidget />
    </aside>
  )
}
