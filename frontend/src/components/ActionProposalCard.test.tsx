import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ActionProposalCard from './ActionProposalCard'
import { useChatStore, type ActionProposal } from '../store/chatStore'
import * as client from '../api/client'

vi.mock('../api/client', () => ({
  confirmAction: vi.fn(),
}))

const PROPOSAL: ActionProposal = {
  proposalId: 'p1',
  action: 'create_micro_action',
  params: { title: '出门散步 10 分钟', category: 'walk', scheduled_at: null },
  summary: '加一条小行动：出门散步 10 分钟',
}

let setPendingProposal: (proposal: ActionProposal | null) => void

beforeEach(() => {
  vi.clearAllMocks()
  setPendingProposal = vi.fn()
  useChatStore.setState({ setPendingProposal })
})

describe('ActionProposalCard', () => {
  it('shows the proposal summary and both action buttons', () => {
    render(<ActionProposalCard proposal={PROPOSAL} />)
    expect(screen.getByText('加一条小行动：出门散步 10 分钟')).toBeInTheDocument()
    expect(screen.getByText('确认')).toBeInTheDocument()
    expect(screen.getByText('取消')).toBeInTheDocument()
  })

  it('calls confirmAction with the exact action and params on confirm', async () => {
    vi.mocked(client.confirmAction).mockResolvedValue({ action: 'create_micro_action', result: {} })
    const user = userEvent.setup()
    render(<ActionProposalCard proposal={PROPOSAL} />)

    await user.click(screen.getByText('确认'))

    expect(client.confirmAction).toHaveBeenCalledWith('create_micro_action', PROPOSAL.params)
    expect(await screen.findByText('已保存 ✓')).toBeInTheDocument()
  })

  it('clears the pending proposal without calling confirmAction when cancelled', async () => {
    const user = userEvent.setup()
    render(<ActionProposalCard proposal={PROPOSAL} />)

    await user.click(screen.getByText('取消'))

    expect(setPendingProposal).toHaveBeenCalledWith(null)
    expect(client.confirmAction).not.toHaveBeenCalled()
  })

  it('shows an error and a retry option when confirmAction fails', async () => {
    vi.mocked(client.confirmAction).mockRejectedValue(new Error('网络错误'))
    const user = userEvent.setup()
    render(<ActionProposalCard proposal={PROPOSAL} />)

    await user.click(screen.getByText('确认'))

    expect(await screen.findByText('网络错误')).toBeInTheDocument()
    expect(screen.getByText('重试')).toBeInTheDocument()
  })
})
