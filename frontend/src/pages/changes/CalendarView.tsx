import { useEffect, useState } from 'react'
import { format, subDays, eachDayOfInterval } from 'date-fns'
import { fetchEmotions, type EmotionOut } from '../../api/client'

const EMOTION_COLOR: Record<string, string> = {
  悲伤: '#6b9bd2',
  焦虑: '#f0a653',
  愤怒: '#e05c5c',
  恐惧: '#9b72cf',
  无助: '#7db8a5',
  孤独: '#5b8dd9',
  疲惫: '#a0a0b0',
  平静: '#52b788',
  希望: '#74c69d',
  麻木: '#b0b0c0',
  其他: '#d0d0d0',
}

function emotionColor(emotion: string | null): string {
  return EMOTION_COLOR[emotion ?? '其他'] ?? '#d0d0d0'
}

function intensityOpacity(intensity: number | null): number {
  return 0.3 + ((intensity ?? 5) / 10) * 0.7
}

export default function CalendarView() {
  const [emotions, setEmotions] = useState<EmotionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchEmotions(30)
      .then(setEmotions)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // 构建日期 → 情绪列表 映射
  const byDay: Record<string, EmotionOut[]> = {}
  for (const e of emotions) {
    const day = e.created_at.slice(0, 10)
    if (!byDay[day]) byDay[day] = []
    byDay[day].push(e)
  }

  const today = new Date()
  const days = eachDayOfInterval({ start: subDays(today, 29), end: today })

  // 图例
  const usedEmotions = [...new Set(emotions.map((e) => e.primary_emotion).filter(Boolean))]

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <div className="max-w-2xl mx-auto px-4 md:px-6 py-6">
      {loading && <p className="text-ink-soft text-sm">加载中…</p>}
      {error && <p className="text-red-500 text-sm">{error}</p>}

      {!loading && !error && (
        <>
          {/* 日历格子 */}
          <div className="grid grid-cols-7 gap-1.5 mb-6">
            {['日', '一', '二', '三', '四', '五', '六'].map((d) => (
              <div key={d} className="text-center text-xs text-ink-soft pb-1">
                {d}
              </div>
            ))}
            {days.map((day) => {
              const key = format(day, 'yyyy-MM-dd')
              const records = byDay[key] ?? []
              const isToday = key === format(today, 'yyyy-MM-dd')

              // 取当天主情绪（强度最高的那条）
              const top = records.sort((a, b) => (b.intensity ?? 0) - (a.intensity ?? 0))[0]

              return (
                <div
                  key={key}
                  title={top ? `${key}\n${top.primary_emotion} · 强度 ${top.intensity}` : key}
                  className={`aspect-square rounded-lg flex items-center justify-center text-xs font-mono tabular-nums
                    ${isToday ? 'ring-2 ring-sage-400' : ''}
                  `}
                  style={{
                    backgroundColor: top
                      ? emotionColor(top.primary_emotion)
                      : '#E0D5D3',
                    opacity: top ? intensityOpacity(top.intensity) + 0.15 : 0.5,
                  }}
                >
                  <span className="text-white font-medium drop-shadow-sm">
                    {format(day, 'd')}
                  </span>
                </div>
              )
            })}
          </div>

          {/* 图例 */}
          {usedEmotions.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-6">
              {usedEmotions.map((em) => (
                <span
                  key={em}
                  className="flex items-center gap-1 text-xs text-ink bg-paper-surface px-2 py-1 rounded-full shadow-soft"
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full inline-block"
                    style={{ backgroundColor: emotionColor(em) }}
                  />
                  {em}
                </span>
              ))}
            </div>
          )}

          {/* 近期列表 */}
          {emotions.length === 0 ? (
            <p className="text-center text-ink-soft text-sm mt-8">
              还没有情绪记录，和 MindPal 聊聊天就会出现这里~
            </p>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-ink-soft font-medium mb-2">最近记录</p>
              {emotions.slice(0, 10).map((e) => (
                <div
                  key={e.id}
                  className="flex items-center gap-3 bg-paper-surface rounded-xl px-4 py-3 shadow-soft"
                >
                  <span
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: emotionColor(e.primary_emotion) }}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-ink">{e.primary_emotion ?? '其他'}</span>
                    {e.triggers.length > 0 && (
                      <span className="text-xs text-ink-soft ml-2">
                        {e.triggers.slice(0, 2).join(' · ')}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <span
                        key={i}
                        className="w-1.5 h-1.5 rounded-full"
                        style={{
                          backgroundColor:
                            i < Math.round((e.intensity ?? 5) / 2)
                              ? emotionColor(e.primary_emotion)
                              : '#E0D5D3',
                        }}
                      />
                    ))}
                  </div>
                  <span className="font-mono text-[11px] tabular-nums text-ink-soft shrink-0">
                    {e.created_at.slice(5, 10)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      </div>
    </div>
  )
}
