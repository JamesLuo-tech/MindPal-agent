import type { LucideIcon } from 'lucide-react'
import { Footprints, Droplets, Utensils, Phone, Wind, BookOpen } from 'lucide-react'

export interface SmallStepTemplate {
  icon: LucideIcon
  label: string
  category: string
}

/** 微目标模板——行为激活用的最小可行动作，点一下就能加进"我的计划" */
export const SMALL_STEP_TEMPLATES: SmallStepTemplate[] = [
  { icon: Footprints, label: '出门散步 10 分钟', category: 'walk' },
  { icon: Droplets, label: '去洗个澡', category: 'shower' },
  { icon: Utensils, label: '好好吃一顿饭', category: 'eat' },
  { icon: Phone, label: '联系一个朋友', category: 'contact_friend' },
  { icon: Wind, label: '做 5 次深呼吸', category: 'breathe' },
  { icon: BookOpen, label: '写下 3 句今天的想法', category: 'journal' },
]
