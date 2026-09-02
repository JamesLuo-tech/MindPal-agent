import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SmallSteps from './SmallSteps'
import * as client from '../api/client'
import type { ScheduleItemOut } from '../api/client'

vi.mock('../api/client', () => ({
  fetchSchedule: vi.fn(),
  createScheduleItem: vi.fn(),
  updateScheduleItem: vi.fn(),
  deleteScheduleItem: vi.fn(),
}))

const SEEDED_ITEM: ScheduleItemOut = {
  id: 'item-1',
  title: '出门散步 10 分钟',
  category: 'walk',
  scheduled_at: null,
  status: 'pending',
  completed_at: null,
  created_at: '2026-09-01T00:00:00Z',
}

async function planList() {
  return within(await screen.findByTestId('plan-list'))
}

function templates() {
  return within(screen.getByTestId('step-templates'))
}

beforeEach(() => {
  vi.mocked(client.fetchSchedule).mockResolvedValue([SEEDED_ITEM])
  vi.mocked(client.createScheduleItem).mockImplementation(async ({ title, category }) => ({
    id: 'item-2', title, category: category ?? null, scheduled_at: null,
    status: 'pending', completed_at: null, created_at: '2026-09-01T00:00:00Z',
  }))
  vi.mocked(client.updateScheduleItem).mockImplementation(async (id, patch) => ({
    ...SEEDED_ITEM, id, ...patch,
  }) as ScheduleItemOut)
  vi.mocked(client.deleteScheduleItem).mockResolvedValue(undefined)
})

describe('SmallSteps', () => {
  it('shows the fetched plan item once loaded', async () => {
    render(<SmallSteps />)
    const list = await planList()
    expect(list.getByText('出门散步 10 分钟')).toBeInTheDocument()
  })

  it('adds a new pending item when a template chip is clicked', async () => {
    const user = userEvent.setup()
    render(<SmallSteps />)
    const list = await planList()

    await user.click(templates().getByText('去洗个澡'))

    expect(await list.findByText('去洗个澡')).toBeInTheDocument()
    expect(client.createScheduleItem).toHaveBeenCalledWith({ title: '去洗个澡', category: 'shower' })
  })

  it('moves an item to 已完成 when its toggle button is clicked', async () => {
    const user = userEvent.setup()
    render(<SmallSteps />)
    const list = await planList()

    await user.click(screen.getByLabelText('标记完成：出门散步 10 分钟'))

    expect(await list.findByText('已完成')).toBeInTheDocument()
    expect(client.updateScheduleItem).toHaveBeenCalledWith('item-1', { status: 'done' })
  })

  it('removes an item when its delete button is clicked', async () => {
    const user = userEvent.setup()
    render(<SmallSteps />)
    await planList()

    await user.click(screen.getByLabelText('删除：出门散步 10 分钟'))

    expect(await screen.findByText('先从上面挑一件小事开始吧')).toBeInTheDocument()
    expect(client.deleteScheduleItem).toHaveBeenCalledWith('item-1')
  })
})
