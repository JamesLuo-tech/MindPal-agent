import type { Message } from '../store/chatStore'

interface Props {
  message: Message
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end mb-4 px-1">
        <div className="max-w-[75%]">
          <div className="px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed whitespace-pre-wrap text-white bg-accent-500">
            {message.content}
          </div>
          <p className="font-mono text-[11px] tabular-nums mt-1 text-right pr-1 text-ink-soft/80">
            {formatTime(message.createdAt)}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-4 px-1">
      <div className="max-w-[80%]">
        <div className="bg-paper-surface text-ink px-4 py-3 rounded-2xl rounded-tl-sm text-sm leading-relaxed whitespace-pre-wrap border border-paper-sunk/50">
          {message.content}
        </div>
        <p className="font-mono text-[11px] tabular-nums text-ink-soft/80 mt-1 pl-1">
          {formatTime(message.createdAt)}
        </p>
      </div>
    </div>
  )
}
