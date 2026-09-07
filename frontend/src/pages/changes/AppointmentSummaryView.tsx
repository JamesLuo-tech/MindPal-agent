import { useState } from 'react'
import { Copy, Check, Download } from 'lucide-react'
import { fetchAppointmentSummary, fetchAppointmentSummaryPdf, type AppointmentSummaryOut } from '../../api/client'

const DAY_OPTIONS = [
  { label: '过去 7 天', value: 7 },
  { label: '过去 14 天', value: 14 },
  { label: '过去 30 天', value: 30 },
]

function toClipboardText(days: number, summary: AppointmentSummaryOut): string {
  const lines = [`过去 ${days} 天的自我记录`, ...summary.bullets.map((b) => `· ${b}`)]
  if (summary.discuss_topics) {
    lines.push('', `想重点讨论：${summary.discuss_topics}`)
  }
  return lines.join('\n')
}

export default function AppointmentSummaryView() {
  const [days, setDays] = useState(14)
  const [discussTopics, setDiscussTopics] = useState('')
  const [summary, setSummary] = useState<AppointmentSummaryOut | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [downloadingPdf, setDownloadingPdf] = useState(false)

  async function handleGenerate() {
    setLoading(true)
    setError('')
    try {
      const result = await fetchAppointmentSummary(days, discussTopics.trim() || undefined)
      setSummary(result)
    } catch (e: any) {
      setError(e.message || '生成失败，请稍后再试')
    } finally {
      setLoading(false)
    }
  }

  function handleCopy() {
    if (!summary) return
    navigator.clipboard.writeText(toClipboardText(days, summary)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  async function handleDownloadPdf() {
    setDownloadingPdf(true)
    setError('')
    try {
      const blob = await fetchAppointmentSummaryPdf(days, discussTopics.trim() || undefined)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'mindpal-appointment-summary.pdf'
      link.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      setError(e.message || 'PDF 生成失败，请稍后再试')
    } finally {
      setDownloadingPdf(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <div className="max-w-2xl mx-auto px-4 md:px-6 py-6 space-y-4">
        <p className="text-sm text-ink-soft leading-relaxed">
          很多人去见医生或心理咨询师时会突然不知道说什么。把想看的时间范围选一下，
          MindPal 会把你自己记录过的数据整理成要点，方便你带去用。
        </p>

        {/* 生成表单 */}
        <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60 space-y-3">
          <div>
            <p className="text-sm font-medium text-ink mb-2">看多久的记录</p>
            <div className="flex gap-2">
              {DAY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setDays(opt.value)}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium transition-colors border-b-2 ${
                    days === opt.value
                      ? 'bg-paper-sunk text-ink border-accent-500'
                      : 'bg-paper-sunk text-ink-soft border-transparent hover:border-accent-300'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-sm font-medium text-ink mb-2">这次想重点讨论什么（可以不填）</p>
            <textarea
              value={discussTopics}
              onChange={(e) => setDiscussTopics(e.target.value)}
              placeholder="比如：注意力下降、持续疲惫"
              rows={2}
              className="w-full bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 resize-none"
            />
          </div>

          {error && <p className="text-red-500 text-sm">{error}</p>}

          <button
            onClick={handleGenerate}
            disabled={loading}
            className="w-full py-2.5 rounded-xl bg-accent-500 text-white text-sm font-medium hover:bg-accent-600 active:scale-[0.98] transition disabled:opacity-50"
          >
            {loading ? '生成中…' : '生成问诊摘要'}
          </button>
        </div>

        {/* 结果卡片 */}
        {summary && (
          <div className="bg-paper-surface rounded-2xl border border-paper-sunk/60 overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-paper-sunk">
              <p className="font-display text-sm font-bold text-ink">问诊摘要</p>
              <div className="flex items-center gap-1">
                <button
                  onClick={handleDownloadPdf}
                  disabled={downloadingPdf}
                  title="下载正式报告 PDF"
                  className="w-8 h-8 flex items-center justify-center rounded-lg text-ink-soft hover:bg-paper-sunk hover:text-ink transition-colors disabled:opacity-50"
                >
                  <Download className={`w-4 h-4 ${downloadingPdf ? 'animate-pulse' : ''}`} />
                </button>
                <button
                  onClick={handleCopy}
                  title="复制到剪贴板"
                  className="w-8 h-8 flex items-center justify-center rounded-lg text-ink-soft hover:bg-paper-sunk hover:text-ink transition-colors"
                >
                  {copied ? <Check className="w-4 h-4 text-sage-600" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="px-5 py-4">
              <p className="text-xs text-ink-soft mb-3">过去 {days} 天的自我记录 · {summary.period}</p>

              <ul className="space-y-2">
                {summary.bullets.map((bullet, i) => (
                  <li key={i} className="flex gap-2 text-sm text-ink leading-relaxed">
                    <span className="text-accent-500 shrink-0">·</span>
                    {bullet}
                  </li>
                ))}
              </ul>

              {summary.discuss_topics && (
                <div className="mt-4 pt-3 border-t border-paper-sunk">
                  <p className="text-xs font-medium text-sage-600 mb-1">想重点讨论</p>
                  <p className="text-sm text-ink">{summary.discuss_topics}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
