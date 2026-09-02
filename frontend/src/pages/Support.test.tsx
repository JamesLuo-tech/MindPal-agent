import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Support from './Support'
import * as client from '../api/client'
import type { SafetyPlanOut, TrustedContactOut } from '../api/client'

vi.mock('../api/client', () => ({
  fetchSafetyPlan: vi.fn(),
  saveSafetyPlan: vi.fn(),
  fetchTrustedContacts: vi.fn(),
  createTrustedContact: vi.fn(),
  deleteTrustedContact: vi.fn(),
}))

const EXISTING_PLAN: SafetyPlanOut = {
  warning_signs: '开始不想说话',
  internal_coping: null,
  distraction_people_places: null,
  help_contacts: null,
  professional_contacts: null,
  safe_environment: null,
  updated_at: '2026-09-01T00:00:00Z',
}

const SEEDED_CONTACT: TrustedContactOut = {
  id: 'c1',
  name: '小李',
  relationship: '朋友',
  phone: '13800000000',
  created_at: '2026-09-01T00:00:00Z',
}

beforeEach(() => {
  vi.mocked(client.fetchSafetyPlan).mockResolvedValue(null)
  vi.mocked(client.saveSafetyPlan).mockResolvedValue(EXISTING_PLAN)
  vi.mocked(client.fetchTrustedContacts).mockResolvedValue([])
  vi.mocked(client.createTrustedContact).mockResolvedValue(SEEDED_CONTACT)
  vi.mocked(client.deleteTrustedContact).mockResolvedValue(undefined)
})

describe('Support', () => {
  it('prefills the safety plan form from an existing plan', async () => {
    vi.mocked(client.fetchSafetyPlan).mockResolvedValue(EXISTING_PLAN)
    render(<Support />)

    expect(await screen.findByDisplayValue('开始不想说话')).toBeInTheDocument()
  })

  it('saves the safety plan and shows a confirmation', async () => {
    const user = userEvent.setup()
    render(<Support />)
    await screen.findByText('保存安全计划')

    const warningSignsInput = screen.getByPlaceholderText('什么样的想法/感受/行为，说明状态在变差？')
    await user.type(warningSignsInput, '开始失眠')
    await user.click(screen.getByText('保存安全计划'))

    expect(client.saveSafetyPlan).toHaveBeenCalledWith(
      expect.objectContaining({ warning_signs: '开始失眠' }),
    )
    expect(await screen.findByText('已保存 ✓')).toBeInTheDocument()
  })

  it('adds a trusted contact and clears the form', async () => {
    const user = userEvent.setup()
    render(<Support />)
    await screen.findByText('添加联系人')

    await user.type(screen.getByPlaceholderText('姓名'), '小李')
    await user.type(screen.getByPlaceholderText('关系'), '朋友')
    await user.type(screen.getByPlaceholderText('电话'), '13800000000')
    await user.click(screen.getByText('添加联系人'))

    expect(client.createTrustedContact).toHaveBeenCalledWith({
      name: '小李', relationship: '朋友', phone: '13800000000',
    })
    expect(await screen.findByText('小李')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('姓名')).toHaveValue('')
  })

  it('removes a trusted contact', async () => {
    vi.mocked(client.fetchTrustedContacts).mockResolvedValue([SEEDED_CONTACT])
    const user = userEvent.setup()
    render(<Support />)

    await screen.findByText('小李')
    await user.click(screen.getByLabelText('删除联系人：小李'))

    expect(client.deleteTrustedContact).toHaveBeenCalledWith('c1')
  })

  it('renders coping tools and professional orgs as static informational content only', async () => {
    render(<Support />)

    expect(await screen.findByText('478 呼吸法')).toBeInTheDocument()
    expect(screen.getByText('北京心理危机研究与干预中心')).toBeInTheDocument()
    expect(screen.getByText('010-82951332').closest('a')).toHaveAttribute('href', 'tel:010-82951332')

    // 明确的范围守卫：这个页面永远不应该出现"转人工"这类现场客服入口
    expect(screen.queryByText(/转人工/)).not.toBeInTheDocument()
  })
})
