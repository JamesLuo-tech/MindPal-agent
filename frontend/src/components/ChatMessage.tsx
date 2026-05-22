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
          <div
            className="px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed whitespace-pre-wrap shadow-sm text-white"
            style={{ backgroundColor: '#E8845A' }}
          >
            {message.content}
          </div>
          <p className="text-xs mt-1 text-right pr-1" style={{ color: '#f0a880' }}>
            {formatTime(message.createdAt)}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start mb-4 px-1">
      <div className="max-w-[80%]">
        <div className="bg-white text-gray-700 px-4 py-3 rounded-2xl rounded-tl-sm text-sm leading-relaxed whitespace-pre-wrap shadow-sm">
          {message.content}
        </div>
        <p className="text-xs text-gray-400 mt-1 pl-1">
          {formatTime(message.createdAt)}
        </p>
      </div>
    </div>
  )
}
