import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Changes from './Changes'
import * as client from '../api/client'
import type { WeeklyReportOut } from '../api/client'

vi.mock('../api/client', () => ({
  fetchEmotions: vi.fn(),
  fetchWeeklyReport: vi.fn(),
  fetchAppointmentSummary: vi.fn(),
  fetchAppointmentSummaryPdf: vi.fn(),
}))

const REPORT: WeeklyReportOut = {
  period: '2026-08-25 ~ 2026-09-01',
  emotion_trend: [],
  key_events: [],
  summary: '这周整体还算平稳，谢谢你一直在说。',
}

beforeEach(() => {
  vi.mocked(client.fetchEmotions).mockResolvedValue([])
  vi.mocked(client.fetchWeeklyReport).mockResolvedValue(REPORT)
})

function renderChanges(initialEntry = '/changes') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Changes />
    </MemoryRouter>,
  )
}

describe('Changes', () => {
  it('shows the calendar view by default', async () => {
    renderChanges()
    expect(await screen.findByText('还没有情绪记录，和 MindPal 聊聊天就会出现这里~')).toBeInTheDocument()
    expect(client.fetchWeeklyReport).not.toHaveBeenCalled()
  })

  it('switches to the trend view when 趋势 is clicked', async () => {
    const user = userEvent.setup()
    renderChanges()
    await screen.findByText('还没有情绪记录，和 MindPal 聊聊天就会出现这里~')

    await user.click(screen.getByText('趋势'))

    expect(await screen.findByText('这周整体还算平稳，谢谢你一直在说。')).toBeInTheDocument()
  })

  it('respects an initial ?view=trend deep link', async () => {
    renderChanges('/changes?view=trend')
    expect(await screen.findByText('这周整体还算平稳，谢谢你一直在说。')).toBeInTheDocument()
  })

  it('switches to the appointment summary view when 问诊摘要 is clicked', async () => {
    const user = userEvent.setup()
    renderChanges()
    await screen.findByText('还没有情绪记录，和 MindPal 聊聊天就会出现这里~')

    await user.click(screen.getByText('问诊摘要'))

    expect(screen.getByText('生成问诊摘要')).toBeInTheDocument()
  })
})
