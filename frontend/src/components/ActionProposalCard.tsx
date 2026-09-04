import { useState } from 'react'
import { Check, X } from 'lucide-react'
import Companion from './Companion'
import { confirmAction } from '../api/client'
import { useChatStore, type ActionProposal } from '../store/chatStore'

/**
 * 聊天里出现的"待确认"卡片——Agent 提议了一个写入动作（记心情、加小行动……），
 * 真正的数据库写入只在用户点了"确认"之后才会发生，点"取消"就单纯关掉，什么都不做。
 */
export default function ActionProposalCard({ proposal }: { proposal: ActionProposal }) {
  const setPendingProposal = useChatStore((s) => s.setPendingProposal)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState('')

  async function handleConfirm() {
    setStatus('saving')
    try {
      await confirmAction(proposal.action, proposal.params)
      setStatus('saved')
      setTimeout(() => setPendingProposal(null), 1200)
    } catch (e: any) {
      setStatus('error')
      setError(e.message || '保存失败，请稍后再试')
    }
  }

  function handleCancel() {
    setPendingProposal(null)
  }

  return (
    <div className="flex justify-start mb-4 px-1">
      <div className="max-w-[85%] bg-paper-surface border border-accent-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-soft">
        <div className="flex items-start gap-2.5">
          <Companion mood={status === 'saved' ? 'happy' : 'idle'} size={22} animate={false} />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-ink leading-relaxed">{proposal.summary}</p>

            {status === 'error' && <p className="text-red-500 text-xs mt-1.5">{error}</p>}

            {status === 'idle' && (
              <div className="flex gap-2 mt-2.5">
                <button
                  onClick={handleConfirm}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-accent-500 text-white text-xs font-medium hover:bg-accent-600 active:scale-95 transition"
                >
                  <Check className="w-3.5 h-3.5" /> 确认
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-paper-sunk text-ink-soft text-xs font-medium hover:text-ink active:scale-95 transition"
                >
                  <X className="w-3.5 h-3.5" /> 取消
                </button>
              </div>
            )}

            {status === 'saving' && (
              <p className="text-ink-soft text-xs mt-2.5 animate-pulse">保存中…</p>
            )}

            {status === 'saved' && (
              <p className="text-sage-600 text-xs mt-2.5">已保存 ✓</p>
            )}

            {status === 'error' && (
              <div className="flex gap-2 mt-2.5">
                <button
                  onClick={handleConfirm}
                  className="px-3 py-1.5 rounded-full bg-accent-500 text-white text-xs font-medium hover:bg-accent-600 active:scale-95 transition"
                >
                  重试
                </button>
                <button
                  onClick={handleCancel}
                  className="px-3 py-1.5 rounded-full bg-paper-sunk text-ink-soft text-xs font-medium hover:text-ink active:scale-95 transition"
                >
                  取消
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
