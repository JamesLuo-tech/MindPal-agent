import { useEffect, useRef, useState } from 'react'
import { format } from 'date-fns'
import { Link } from 'react-router-dom'
import { CheckCircle2, Circle } from 'lucide-react'
import Companion, { type CompanionMood } from '../components/Companion'
import {
  fetchToday,
  saveCheckin,
  updateScheduleItem,
  type TodaySnapshotOut,
} from '../api/client'

const SLEEP_DEBOUNCE_MS = 500
const SMALL_WIN_DEBOUNCE_MS = 800

export default function Today() {
  const [snapshot, setSnapshot] = useState<TodaySnapshotOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [mood, setMood] = useState<number | null>(null)
  const [energy, setEnergy] = useState<number | null>(null)
  const [sleepHours, setSleepHours] = useState<number | null>(null)
  const [smallWin, setSmallWin] = useState('')

  const sleepTimer = useRef<ReturnType<typeof setTimeout>>()
  const smallWinTimer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    fetchToday()
      .then((s) => {
        setSnapshot(s)
        setMood(s.checkin?.mood ?? null)
        setEnergy(s.checkin?.energy ?? null)
        setSleepHours(s.checkin?.sleep_hours ?? null)
        setSmallWin(s.checkin?.small_win ?? '')
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const companionMood: CompanionMood = mood === null ? 'idle' : mood >= 4 ? 'happy' : 'idle'

  function pickMood(v: number) {
    setMood(v)
    saveCheckin({ mood: v }).catch((e) => setError(e.message))
  }

  function pickEnergy(v: number) {
    setEnergy(v)
    saveCheckin({ energy: v }).catch((e) => setError(e.message))
  }

  function nudgeSleep(delta: number) {
    setSleepHours((h) => {
      const next = Math.min(24, Math.max(0, (h ?? (delta > 0 ? 6.5 : 7)) + delta))
      clearTimeout(sleepTimer.current)
      sleepTimer.current = setTimeout(() => {
        saveCheckin({ sleep_hours: next }).catch((e) => setError(e.message))
      }, SLEEP_DEBOUNCE_MS)
      return next
    })
  }

  function editSmallWin(value: string) {
    setSmallWin(value)
    clearTimeout(smallWinTimer.current)
    smallWinTimer.current = setTimeout(() => {
      saveCheckin({ small_win: value }).catch((e) => setError(e.message))
    }, SMALL_WIN_DEBOUNCE_MS)
  }

  async function completeNextItem() {
    if (!snapshot?.next_schedule_item) return
    const id = snapshot.next_schedule_item.id
    setSnapshot((s) => (s ? { ...s, next_schedule_item: null } : s))
    try {
      await updateScheduleItem(id, { status: 'done' })
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* 页头 */}
      <div className="flex items-center px-6 md:px-10 py-5 border-b border-paper-sunk shrink-0">
        <Companion mood={companionMood} size={30} animate={false} />
        <div className="ml-3">
          <h1 className="font-display text-2xl font-bold text-ink leading-tight">今日</h1>
          <p className="font-mono text-ink-soft/80 text-sm mt-0.5 tabular-nums">
            {format(new Date(), 'yyyy-MM-dd EEEE')}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto bg-paper">
        <div className="max-w-2xl mx-auto px-4 md:px-6 py-6 space-y-4">
        {loading && <p className="text-ink-soft text-sm">加载中…</p>}
        {error && <p className="text-red-500 text-sm">{error}</p>}

        {!loading && (
          <>
            {/* 心情 / 精力 / 睡眠 快速记录 */}
            <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60 space-y-4">
              <div>
                <p className="text-sm font-medium text-ink mb-2">心情怎么样？</p>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      onClick={() => pickMood(v)}
                      className={`flex-1 py-2 rounded-xl text-sm font-mono tabular-nums transition active:scale-95 border-b-2 ${
                        mood === v
                          ? 'bg-paper-sunk text-ink border-accent-500'
                          : 'bg-paper-sunk text-ink-soft border-transparent hover:border-accent-300'
                      }`}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="text-sm font-medium text-ink mb-2">精力如何？</p>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      onClick={() => pickEnergy(v)}
                      className={`flex-1 py-2 rounded-xl text-sm font-mono tabular-nums transition active:scale-95 border-b-2 ${
                        energy === v
                          ? 'bg-paper-sunk text-ink border-accent-500'
                          : 'bg-paper-sunk text-ink-soft border-transparent hover:border-accent-300'
                      }`}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="text-sm font-medium text-ink mb-2">昨晚睡了多久？</p>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => nudgeSleep(-0.5)}
                    aria-label="减少半小时"
                    className="w-8 h-8 rounded-full bg-paper-sunk text-ink flex items-center justify-center shrink-0 transition hover:bg-accent-50 active:scale-90"
                  >
                    −
                  </button>
                  <span className="font-mono tabular-nums text-sm text-ink w-14 text-center">
                    {sleepHours ?? '—'} 小时
                  </span>
                  <button
                    onClick={() => nudgeSleep(0.5)}
                    aria-label="增加半小时"
                    className="w-8 h-8 rounded-full bg-paper-sunk text-ink flex items-center justify-center shrink-0 transition hover:bg-accent-50 active:scale-90"
                  >
                    +
                  </button>
                </div>
              </div>
            </div>

            {/* 今天的一件小事 */}
            <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
              <p className="text-sm font-medium text-ink mb-2">今天想记的一件小事</p>
              <textarea
                value={smallWin}
                onChange={(e) => editSmallWin(e.target.value)}
                placeholder="哪怕很小的一件事也可以……"
                rows={2}
                className="w-full bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 resize-none"
              />
            </div>

            {/* 下一个日程 */}
            <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
              <p className="text-sm font-medium text-ink mb-2">下一个日程</p>
              {snapshot?.next_schedule_item ? (
                <div className="flex items-center gap-3">
                  <button
                    onClick={completeNextItem}
                    aria-label={`标记完成：${snapshot.next_schedule_item.title}`}
                    className="shrink-0 text-accent-500 transition-transform active:scale-90"
                  >
                    <Circle className="w-5 h-5" strokeWidth={2} />
                  </button>
                  <span className="text-sm text-ink flex-1">{snapshot.next_schedule_item.title}</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-sm text-ink-soft">
                  <CheckCircle2 className="w-4 h-4 text-sage-500" />
                  暂时没有安排，休息一下也很好
                </div>
              )}
              <Link to="/steps" className="inline-block mt-3 text-xs text-accent-500 hover:text-accent-600">
                查看全部 →
              </Link>
            </div>

            {/* 个性化推荐 */}
            {snapshot?.recommendation && (
              <div className="bg-sage-300/25 border border-sage-400/30 rounded-2xl px-5 py-4">
                <p className="text-xs font-medium text-sage-600 mb-1.5">给今天的你</p>
                <p className="text-sm text-ink leading-relaxed">{snapshot.recommendation}</p>
              </div>
            )}
          </>
        )}
        </div>
      </div>
    </div>
  )
}
