import { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { fetchWeeklyReport, type WeeklyReportOut } from '../api/client'

const EMOTION_DOT: Record<string, string> = {
  悲伤: '#6b9bd2', 焦虑: '#f0a653', 愤怒: '#e05c5c',
  恐惧: '#9b72cf', 无助: '#7db8a5', 孤独: '#5b8dd9',
  疲惫: '#a0a0b0', 平静: '#52b788', 希望: '#74c69d',
  麻木: '#b0b0c0', 其他: '#d0d0d0',
}

function EmotionDot({ emotion }: { emotion: string }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full mr-1.5"
      style={{ backgroundColor: EMOTION_DOT[emotion] ?? '#d0d0d0' }}
    />
  )
}

export default function WeeklyReport() {
  const [report, setReport] = useState<WeeklyReportOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchWeeklyReport()
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 p-4 max-w-2xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-800 mb-1">本周报告</h1>
      {report && (
        <p className="text-gray-400 text-xs mb-5">{report.period}</p>
      )}

      {loading && <p className="text-gray-400 text-sm">生成中…</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {report && (
        <>
          {/* LLM 摘要 */}
          <div className="bg-white rounded-2xl px-5 py-4 shadow-sm mb-5">
            <p className="text-sm text-gray-700 leading-relaxed">{report.summary}</p>
          </div>

          {/* 情绪强度折线图 */}
          {report.emotion_trend.length > 0 ? (
            <div className="bg-white rounded-2xl px-4 py-4 shadow-sm mb-5">
              <p className="text-sm font-medium text-gray-600 mb-3">情绪强度趋势</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={report.emotion_trend} margin={{ left: -20, right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: '#9ca3af' }}
                    tickFormatter={(v: string) => v.slice(5)}
                  />
                  <YAxis
                    domain={[0, 10]}
                    tick={{ fontSize: 11, fill: '#9ca3af' }}
                    ticks={[0, 2, 4, 6, 8, 10]}
                  />
                  <Tooltip
                    formatter={(value: number, _name: string) => [value, '情绪强度']}
                    labelFormatter={(label: string) => label}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="avg_intensity"
                    stroke="#6b9bd2"
                    strokeWidth={2}
                    dot={{ r: 4, fill: '#6b9bd2' }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>

              {/* 每天主情绪标注 */}
              <div className="flex flex-wrap gap-2 mt-3">
                {report.emotion_trend.map((p) => (
                  <span key={p.date} className="text-xs text-gray-500 flex items-center">
                    <EmotionDot emotion={p.dominant_emotion} />
                    {p.date.slice(5)} {p.dominant_emotion}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-2xl px-5 py-8 shadow-sm mb-5 text-center">
              <p className="text-gray-400 text-sm">本周暂无情绪数据</p>
            </div>
          )}

          {/* 关键事件 */}
          {report.key_events.length > 0 && (
            <div className="bg-white rounded-2xl px-5 py-4 shadow-sm">
              <p className="text-sm font-medium text-gray-600 mb-3">本周记录</p>
              <div className="space-y-2">
                {report.key_events.map((ev, i) => (
                  <div key={i} className="flex gap-3 text-sm">
                    <span className="text-gray-400 shrink-0 w-16">{ev.date.slice(5)}</span>
                    <span className="text-gray-500 shrink-0 bg-gray-100 px-1.5 py-0.5 rounded text-xs h-fit">
                      {ev.type}
                    </span>
                    <span className="text-gray-700">{ev.content}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {!loading && !error && !report && (
        <p className="text-center text-gray-400 text-sm mt-12">
          和 MindPal 聊聊天，这里就会出现你的情绪报告~
        </p>
      )}
    </div>
  )
}
