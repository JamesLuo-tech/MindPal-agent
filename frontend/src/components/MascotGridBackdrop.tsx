import { useMemo } from 'react'

type MiniMood = 'idle' | 'happy' | 'thinking'
const MOOD_CYCLE: MiniMood[] = ['idle', 'happy', 'thinking', 'idle', 'happy', 'idle']

function MiniMascot({ mood, delay, gradientId }: { mood: MiniMood; delay: number; gradientId: string }) {
  return (
    <div className="grid-mascot" style={{ animationDelay: `${delay}s` }}>
      <svg viewBox="0 0 100 100" width="44" height="44" aria-hidden="true">
        <defs>
          <radialGradient id={gradientId} cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#DBA85F" />
            <stop offset="100%" stopColor="#A6631F" />
          </radialGradient>
        </defs>
        <ellipse cx="50" cy="54" rx="34" ry="32" fill={`url(#${gradientId})`} />
        <ellipse cx="38" cy="40" rx="9" ry="6" fill="#FBF1E4" opacity="0.3" />
        <ellipse cx="39" cy="50" rx="3.6" ry="4.4" fill="#2B2229" />
        <ellipse cx="61" cy="50" rx="3.6" ry="4.4" fill="#2B2229" />
        {mood === 'happy' && <path d="M37 62 Q50 78 63 62 Q50 70 37 62 Z" fill="#2B2229" />}
        {mood === 'idle' && (
          <path d="M41 64 Q50 70 59 64" fill="none" stroke="#2B2229" strokeWidth="3" strokeLinecap="round" />
        )}
        {mood === 'thinking' && <ellipse cx="50" cy="65" rx="3.4" ry="4.2" fill="#2B2229" />}
      </svg>
    </div>
  )
}

/**
 * 满铺的品牌小人网格背景——只用在登录相关的弹窗/浮层背后（比如登录卡片、
 * 移动端登录弹窗），不是全局背景。数量固定但表情/摆动节奏错开，避免机械重复感。
 */
export default function MascotGridBackdrop({ className = '' }: { className?: string }) {
  const icons = useMemo(
    () =>
      Array.from({ length: 28 }, (_, i) => ({
        mood: MOOD_CYCLE[i % MOOD_CYCLE.length],
        delay: (i * 0.37) % 3.2,
      })),
    [],
  )

  return (
    <div className={`absolute inset-0 overflow-hidden bg-[#1B1310] ${className}`} aria-hidden="true">
      <div className="grid-mascot-wall opacity-90">
        {icons.map((icon, i) => (
          <MiniMascot key={i} mood={icon.mood} delay={icon.delay} gradientId={`mini-body-${i}`} />
        ))}
      </div>
    </div>
  )
}
