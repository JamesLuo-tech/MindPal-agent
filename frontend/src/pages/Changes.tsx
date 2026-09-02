import { useSearchParams } from 'react-router-dom'
import CalendarView from './changes/CalendarView'
import TrendView from './changes/TrendView'

export default function Changes() {
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get('view') === 'trend' ? 'trend' : 'calendar'

  function setView(v: 'calendar' | 'trend') {
    setSearchParams(v === 'calendar' ? {} : { view: v })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 md:px-10 py-5 shrink-0 border-b border-paper-sunk">
        <h1 className="font-display text-xl font-bold text-ink mb-0.5">变化</h1>
        <p className="text-ink-soft text-sm mb-3">看看这段时间的变化</p>

        {/* 分段控件 */}
        <div className="inline-flex bg-paper-sunk rounded-full p-1">
          <button
            onClick={() => setView('calendar')}
            className={`px-4 py-1.5 rounded-full text-xs font-medium transition-colors ${
              view === 'calendar' ? 'bg-paper-surface shadow-soft text-ink' : 'text-ink-soft'
            }`}
          >
            日历
          </button>
          <button
            onClick={() => setView('trend')}
            className={`px-4 py-1.5 rounded-full text-xs font-medium transition-colors ${
              view === 'trend' ? 'bg-paper-surface shadow-soft text-ink' : 'text-ink-soft'
            }`}
          >
            趋势
          </button>
        </div>
      </div>

      {view === 'calendar' ? <CalendarView /> : <TrendView />}
    </div>
  )
}
