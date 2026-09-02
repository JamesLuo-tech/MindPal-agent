import { useEffect, useRef, useState } from 'react'

export type CompanionMood = 'idle' | 'thinking' | 'happy'

interface Props {
  mood?: CompanionMood
  /** 是否在父容器内自由飘动（父容器需要 position: relative 且有明确尺寸） */
  wander?: boolean
  /** 是否启用浮动/眨眼/闪烁动画；页头小尺寸用途传 false */
  animate?: boolean
  size?: number
  className?: string
}

/**
 * MindPal 的陪伴小人形象。
 * 情绪跟随对话状态变化（idle / thinking / happy），
 * 在登录页里安静地在背景漂浮，在聊天页里随 Agent 的状态呼吸。
 */
export default function Companion({ mood = 'idle', wander = false, animate = true, size = 96, className = '' }: Props) {
  const [pos, setPos] = useState({ x: 50, y: 45 })
  const reduceMotion = useRef(
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    if (!wander || reduceMotion.current) return
    const pickTarget = () => {
      // 留出边距，避免小人贴边或被裁切
      const x = 12 + Math.random() * 76
      const y = 10 + Math.random() * 70
      setPos({ x, y })
    }
    pickTarget()
    const id = setInterval(pickTarget, 5200)
    return () => clearInterval(id)
  }, [wander])

  const wrapperStyle: React.CSSProperties = wander
    ? {
        position: 'absolute',
        left: `${pos.x}%`,
        top: `${pos.y}%`,
        transition: reduceMotion.current ? undefined : 'left 5s ease-in-out, top 5s ease-in-out',
      }
    : {}

  return (
    <div
      style={wrapperStyle}
      className={`pointer-events-none select-none ${wander ? '' : 'relative'} ${className}`}
    >
      <div className={animate && !reduceMotion.current ? 'companion-float' : ''} style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden="true">
          <defs>
            <radialGradient id="companion-body" cx="35%" cy="30%" r="75%">
              <stop offset="0%" stopColor="#DBA85F" />
              <stop offset="100%" stopColor="#A6631F" />
            </radialGradient>
          </defs>

          {/* 思考态的呼吸光环 */}
          {mood === 'thinking' && animate && (
            <circle cx="50" cy="52" r="38" fill="none" stroke="#8FB09E" strokeWidth="2.5" className="companion-pulse" />
          )}

          {/* 伴随的小火花——只在较大尺寸且开启动画时显示 */}
          {animate && size >= 64 && (
            <path
              d="M82 20 L83.6 25.6 L89 27 L83.6 28.4 L82 34 L80.4 28.4 L75 27 L80.4 25.6 Z"
              fill="#DBA85F"
              className={reduceMotion.current ? '' : 'companion-twinkle'}
            />
          )}

          {/* 身体 */}
          <ellipse cx="50" cy="54" rx="34" ry="32" fill="url(#companion-body)" />
          {/* 高光 */}
          <ellipse cx="38" cy="40" rx="9" ry="6" fill="#FBF1E4" opacity="0.35" />
          {/* 腮红 */}
          <ellipse cx="28" cy="60" rx="5" ry="3.2" fill="#703D12" opacity="0.18" />
          <ellipse cx="72" cy="60" rx="5" ry="3.2" fill="#703D12" opacity="0.18" />

          {/* 眼睛 */}
          <ellipse cx="39" cy="50" rx="3.6" ry="4.4" fill="#2B2229" className={animate && !reduceMotion.current ? 'companion-blink' : ''} />
          <ellipse cx="61" cy="50" rx="3.6" ry="4.4" fill="#2B2229" className={animate && !reduceMotion.current ? 'companion-blink' : ''} style={{ animationDelay: '0.15s' }} />

          {/* 嘴巴：随心情变化 */}
          {mood === 'happy' && (
            <path d="M37 62 Q50 78 63 62 Q50 70 37 62 Z" fill="#2B2229" />
          )}
          {mood === 'idle' && (
            <path d="M41 64 Q50 70 59 64" fill="none" stroke="#2B2229" strokeWidth="3" strokeLinecap="round" />
          )}
          {mood === 'thinking' && (
            <ellipse cx="50" cy="65" rx="3.4" ry="4.2" fill="#2B2229" />
          )}
        </svg>
      </div>
    </div>
  )
}
