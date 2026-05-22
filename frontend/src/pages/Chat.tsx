import { useEffect, useRef } from 'react'
import { useChatStore } from '../store/chatStore'
import { useChat } from '../hooks/useChat'
import ChatMessage from '../components/ChatMessage'
import ChatInput from '../components/ChatInput'
import ToolUseIndicator from '../components/ToolUseIndicator'
import { createConversation } from '../api/client'

export default function Chat() {
  const {
    messages, streaming, streamingContent, activeTool,
    activeConversationId, setActiveConversation,
    voiceEnabled, setVoiceEnabled,
  } = useChatStore()
  const { sendMessage } = useChat()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (activeConversationId) return
    createConversation()
      .then((conv) => setActiveConversation(conv.id))
      .catch(console.error)
  }, [activeConversationId, setActiveConversation])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, activeTool])

  return (
    /* 外层：暖桃渐变背景，居中卡片 */
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-lg h-[calc(100vh-2rem)] max-h-[860px] flex flex-col rounded-3xl overflow-hidden shadow-2xl">

        {/* 顶栏：珊瑚渐变 */}
        <div className="flex items-center px-5 py-4 shrink-0" style={{ background: 'linear-gradient(to right, #E8845A, #f0935f)' }}>
          {/* 左：心形图标 + 标题 */}
          <div className="w-10 h-10 rounded-full flex items-center justify-center mr-3 shrink-0" style={{ backgroundColor: 'rgba(180,90,50,0.35)' }}>
            <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5
                       2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09
                       C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5
                       c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
            </svg>
          </div>
          <div className="flex-1">
            <h1 className="text-white font-semibold text-base leading-tight">MindPal</h1>
            <p className="text-white/75 text-xs mt-0.5">我会一直陪伴着你</p>
          </div>

          {/* 右：语音开关（✦ 闪烁星形） */}
          <button
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            title={voiceEnabled ? '关闭语音' : '开启语音'}
            className="w-9 h-9 flex items-center justify-center rounded-full transition-colors hover:bg-white/20"
          >
            {voiceEnabled ? (
              <svg className="w-5 h-5 text-white drop-shadow" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
              </svg>
            ) : (
              /* 4角星 sparkle — 和设计图一致 */
              <svg className="w-5 h-5 text-white/80" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2 L13.5 10.5 L22 12 L13.5 13.5 L12 22 L10.5 13.5 L2 12 L10.5 10.5 Z"/>
              </svg>
            )}
          </button>
        </div>

        {/* 消息区：暖白背景 */}
        <div className="flex-1 overflow-y-auto px-4 py-5 space-y-0 bg-[#FAF7F4]">
          {messages.length === 0 && !streaming && (
            <p className="text-center text-gray-400 text-sm mt-16">
              嗨，有什么想说的吗？
            </p>
          )}

          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}

          {activeTool && (
            <ToolUseIndicator tool={activeTool.tool} status={activeTool.status} />
          )}

          {/* 流式输出中 */}
          {streaming && streamingContent && (
            <ChatMessage
              message={{
                id: 'streaming',
                role: 'assistant',
                content: streamingContent,
                createdAt: new Date(),
              }}
            />
          )}
          {streaming && !streamingContent && !activeTool && (
            <div className="flex justify-start mb-4 px-1">
              <div className="bg-white px-4 py-3 rounded-2xl rounded-tl-sm shadow-sm">
                <span className="text-gray-400 text-sm animate-pulse">……</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <ChatInput onSend={sendMessage} disabled={streaming} />
      </div>
    </div>
  )
}
