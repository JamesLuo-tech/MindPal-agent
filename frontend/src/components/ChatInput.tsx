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
    <div className="px-4 pt-3 pb-3 bg-paper-surface">
      <div className="flex items-end gap-3">
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="在这里分享你的感受…"
          disabled={disabled}
          className="flex-1 resize-none rounded-2xl bg-paper-sunk px-4 py-3 text-sm text-ink placeholder-ink-soft/60 focus:outline-none focus:ring-2 focus:ring-accent-300 disabled:opacity-50 max-h-[120px] overflow-y-auto leading-relaxed"
        />
        <button
          onClick={handleSend}
          disabled={!text.trim() || disabled}
          className="w-10 h-10 rounded-full bg-accent-500 hover:bg-accent-600 disabled:opacity-40 active:scale-95 transition flex items-center justify-center shrink-0"
        >
          <svg className="w-4 h-4 text-white translate-x-0.5 -translate-y-0.5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
    </div>
  )
}
