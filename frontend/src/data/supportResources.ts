import type { LucideIcon } from 'lucide-react'
import { Wind, Eye, PenLine, Snowflake } from 'lucide-react'

export interface CopingTool {
  icon: LucideIcon
  title: string
  description: string
}

/** 应对工具——纯展示的静态引导内容，不调用任何接口 */
export const COPING_TOOLS: CopingTool[] = [
  {
    icon: Wind,
    title: '478 呼吸法',
    description: '吸气 4 秒，屏住 7 秒，缓缓呼气 8 秒。重复几轮，让神经系统慢下来。',
  },
  {
    icon: Eye,
    title: '5-4-3-2-1 着陆练习',
    description: '说出你看到的 5 样东西、听到的 4 种声音、摸到的 3 种触感、闻到的 2 种气味、尝到的 1 种味道。',
  },
  {
    icon: PenLine,
    title: '把它写下来',
    description: '不用有逻辑，想到什么写什么。写下来本身就是一种释放。',
  },
  {
    icon: Snowflake,
    title: '冰水/冷刺激',
    description: '用冷水拍脸，或者握一会儿冰块。强烈的躯体感受能帮你从情绪漩涡里抽离出来。',
  },
]

export interface ProfessionalOrg {
  name: string
  phone: string
  hours: string
  description: string
}

/** 专业机构与热线——静态信息，仅供拨打，不做任何"转人工"跳转 */
export const PROFESSIONAL_ORGS: ProfessionalOrg[] = [
  {
    name: '北京心理危机研究与干预中心',
    phone: '010-82951332',
    hours: '24 小时',
    description: '全国性心理援助与危机干预热线，任何时候都可以拨打。',
  },
  {
    name: '全国心理援助热线',
    phone: '12356',
    hours: '24 小时',
    description: '国家卫健委统一心理援助热线，覆盖全国。',
  },
  {
    name: '希望 24 热线',
    phone: '400-161-9995',
    hours: '24 小时',
    description: '专注自杀危机干预与心理支持的公益热线。',
  },
]
