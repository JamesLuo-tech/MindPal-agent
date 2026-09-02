import { Home, MessageCircle, Footprints, TrendingUp, LifeBuoy } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

/** 5 个 tab 的导航配置，桌面侧边栏和移动端底部栏共用同一份，避免两处各写一套 */
export const NAV_ITEMS: NavItem[] = [
  { to: '/today', label: '今日', icon: Home },
  { to: '/chat', label: '聊聊', icon: MessageCircle },
  { to: '/steps', label: '小步行动', icon: Footprints },
  { to: '/changes', label: '变化', icon: TrendingUp },
  { to: '/support', label: '支持', icon: LifeBuoy },
]
