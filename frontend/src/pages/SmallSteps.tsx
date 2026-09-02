import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import Companion from '../components/Companion'
import { SMALL_STEP_TEMPLATES } from '../data/smallSteps'
import {
  fetchSchedule,
  createScheduleItem,
  updateScheduleItem,
  deleteScheduleItem,
  type ScheduleItemOut,
} from '../api/client'

export default function SmallSteps() {
  const [items, setItems] = useState<ScheduleItemOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSchedule()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  async function addFromTemplate(title: string, category: string) {
    try {
      const created = await createScheduleItem({ title, category })
      setItems((prev) => [...prev, created])
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function toggleDone(item: ScheduleItemOut) {
    const nextStatus = item.status === 'done' ? 'pending' : 'done'
    // 乐观更新
    setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, status: nextStatus } : it)))
    try {
      const updated = await updateScheduleItem(item.id, { status: nextStatus })
      setItems((prev) => prev.map((it) => (it.id === item.id ? updated : it)))
    } catch (e: any) {
      setError(e.message)
      setItems((prev) => prev.map((it) => (it.id === item.id ? item : it))) // 回滚
    }
  }

  async function remove(id: string) {
    const prevItems = items
    setItems((prev) => prev.filter((it) => it.id !== id))
    try {
      await deleteScheduleItem(id)
    } catch (e: any) {
      setError(e.message)
      setItems(prevItems) // 回滚
    }
  }

  const pending = items.filter((it) => it.status === 'pending')
  const done = items.filter((it) => it.status === 'done')

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 md:px-10 py-5 shrink-0 border-b border-paper-sunk">
        <h1 className="font-display text-2xl font-bold text-ink mb-0.5">小步行动</h1>
        <p className="text-ink-soft/80 text-sm">先做一件小小的事</p>
      </div>

      <div className="flex-1 overflow-y-auto bg-paper">
        <div className="max-w-2xl mx-auto px-4 md:px-6 py-6 space-y-5">
        {error && <p className="text-red-500 text-sm">{error}</p>}

        {/* 模板 chips */}
        <div>
          <p className="text-sm font-medium text-ink mb-2">试试这些</p>
          <div className="flex flex-wrap gap-2" data-testid="step-templates">
            {SMALL_STEP_TEMPLATES.map(({ icon: Icon, label, category }) => (
              <button
                key={category}
                onClick={() => addFromTemplate(label, category)}
                className="flex items-center gap-1.5 bg-paper-surface text-ink text-xs px-3 py-2 rounded-lg border border-paper-sunk/60 hover:bg-accent-50 transition-colors"
              >
                <Icon className="w-3.5 h-3.5 text-accent-500" strokeWidth={2} />
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* 我的计划 */}
        <div>
          <p className="text-sm font-medium text-ink mb-2">我的计划</p>

          {loading ? (
            <p className="text-ink-soft text-sm">加载中…</p>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center py-8">
              <Companion mood="idle" size={72} />
              <p className="text-ink-soft text-sm mt-3">先从上面挑一件小事开始吧</p>
            </div>
          ) : (
            <div className="space-y-2" data-testid="plan-list">
              {pending.map((it) => (
                <div key={it.id} className="flex items-center gap-3 bg-paper-surface rounded-xl px-4 py-3 border border-paper-sunk/60">
                  <button
                    onClick={() => toggleDone(it)}
                    aria-label={`标记完成：${it.title}`}
                    className="w-5 h-5 rounded-full border-2 border-accent-400 shrink-0 transition-transform hover:bg-accent-50 active:scale-90"
                  />
                  <span className="text-sm text-ink flex-1">{it.title}</span>
                  <button
                    onClick={() => remove(it.id)}
                    aria-label={`删除：${it.title}`}
                    className="text-ink-soft hover:text-red-500 shrink-0 transition-transform active:scale-90"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}

              {done.length > 0 && (
                <>
                  <p className="text-xs text-ink-soft mt-4 mb-1">已完成</p>
                  {done.map((it) => (
                    <div key={it.id} className="flex items-center gap-3 bg-paper-surface/60 rounded-xl px-4 py-3">
                      <button
                        onClick={() => toggleDone(it)}
                        aria-label={`取消完成：${it.title}`}
                        className="w-5 h-5 rounded-full bg-sage-500 flex items-center justify-center shrink-0 transition-transform active:scale-90"
                      >
                        <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                          <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </button>
                      <span className="text-sm text-ink-soft flex-1 line-through">{it.title}</span>
                      <button
                        onClick={() => remove(it.id)}
                        aria-label={`删除：${it.title}`}
                        className="text-ink-soft hover:text-red-500 shrink-0 transition-transform active:scale-90"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
