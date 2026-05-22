import { useState, useRef } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled?: boolean
}

export default function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function handleSend() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleInput() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }

  return (
    <div className="px-4 pt-3 pb-2 bg-white/80 backdrop-blur-sm">
      <div className="flex items-end gap-3">
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="在这里分享你的感受..."
          disabled={disabled}
          className="flex-1 resize-none rounded-full border bg-white px-5 py-3 text-sm text-gray-700 placeholder-gray-400 focus:outline-none disabled:opacity-50 max-h-[120px] overflow-y-auto leading-relaxed"
          style={{ borderColor: '#f5c5a8' }}
        />
        <button
          onClick={handleSend}
          disabled={!text.trim() || disabled}
          className="w-11 h-11 rounded-full disabled:opacity-40 transition-colors flex items-center justify-center shrink-0 shadow-md"
          style={{ backgroundColor: '#E8845A' }}
        >
          {/* 纸飞机图标 */}
          <svg className="w-5 h-5 text-white translate-x-0.5 -translate-y-0.5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
      <p className="text-center text-xs text-gray-400 mt-2 mb-1">你的感受很重要，请放心倾诉</p>
    </div>
  )
}
