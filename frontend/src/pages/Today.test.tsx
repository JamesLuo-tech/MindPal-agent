import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Today from './Today'
import * as client from '../api/client'
import type { TodaySnapshotOut } from '../api/client'

vi.mock('../api/client', () => ({
  fetchToday: vi.fn(),
  saveCheckin: vi.fn(),
  updateScheduleItem: vi.fn(),
}))

const BASE_SNAPSHOT: TodaySnapshotOut = {
  checkin: null,
  next_schedule_item: {
    id: 'item-1',
    title: '出门散步 10 分钟',
    category: 'walk',
    scheduled_at: null,
    status: 'pending',
    completed_at: null,
    created_at: '2026-09-01T00:00:00Z',
  },
  recommendation: '今天也要对自己温柔一点。',
}

function renderToday() {
  return render(
    <MemoryRouter>
      <Today />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(client.fetchToday).mockResolvedValue(BASE_SNAPSHOT)
  vi.mocked(client.saveCheckin).mockResolvedValue({} as any)
  vi.mocked(client.updateScheduleItem).mockResolvedValue({} as any)
})

describe('Today', () => {
  it('loads the snapshot and shows the recommendation', async () => {
    renderToday()
    expect(await screen.findByText('今天也要对自己温柔一点。')).toBeInTheDocument()
  })

  it('saves mood via the API when a value is picked', async () => {
    const user = userEvent.setup()
    renderToday()
    await screen.findByText('今天也要对自己温柔一点。')

    const moodButtons = screen.getAllByRole('button', { name: /^[1-5]$/ })
    await user.click(moodButtons[3]) // "4"

    expect(moodButtons[3]).toHaveClass('border-accent-500')
    expect(client.saveCheckin).toHaveBeenCalledWith({ mood: 4 })
  })

  it('prefills mood/energy/sleep from an existing checkin', async () => {
    vi.mocked(client.fetchToday).mockResolvedValue({
      ...BASE_SNAPSHOT,
      checkin: {
        id: 'c1', checkin_date: '2026-09-01', mood: 3, energy: 2,
        sleep_hours: 6.5, small_win: '喝了杯奶茶', created_at: '2026-09-01T00:00:00Z',
      },
    })
    renderToday()

    expect(await screen.findByDisplayValue('喝了杯奶茶')).toBeInTheDocument()
    expect(screen.getByText('6.5 小时')).toBeInTheDocument()
  })

  it('marks the next schedule item done and shows the empty state', async () => {
    const user = userEvent.setup()
    renderToday()
    await screen.findByText('出门散步 10 分钟')

    await user.click(screen.getByLabelText('标记完成：出门散步 10 分钟'))

    expect(screen.getByText('暂时没有安排，休息一下也很好')).toBeInTheDocument()
    expect(client.updateScheduleItem).toHaveBeenCalledWith('item-1', { status: 'done' })
  })

  it('shows an error message when loading fails', async () => {
    vi.mocked(client.fetchToday).mockRejectedValue(new Error('网络错误'))
    renderToday()
    expect(await screen.findByText('网络错误')).toBeInTheDocument()
  })
})
