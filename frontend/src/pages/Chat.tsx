import { useEffect, useMemo, useRef } from 'react'
import { useChatStore } from '../store/chatStore'
import { useChat } from '../hooks/useChat'
import ChatMessage from '../components/ChatMessage'
import ChatInput from '../components/ChatInput'
import ToolUseIndicator from '../components/ToolUseIndicator'
import Companion, { type CompanionMood } from '../components/Companion'
import { createConversation } from '../api/client'

/** 按现在几点，换一句不那么通用的问候——比一句固定的"嗨"更像真的在留意你 */
function greetingForNow(): string {
  const h = new Date().getHours()
  if (h < 5) return '这么晚了还没睡，是有什么事让你还醒着吗'
  if (h < 11) return '早啊，今天感觉怎么样'
  if (h < 14) return '中午好，饭吃了吗'
  if (h < 18) return '这会儿状态还好吗'
  if (h < 23) return '晚上好，今天过得怎么样'
  return '这么晚了还没睡，是有什么事让你还醒着吗'
}

const STARTER_PROMPTS = ['最近有点累', '睡不着', '就是想找人说说话']

export default function Chat() {
  const {
    messages, streaming, streamingContent, activeTool,
    activeConversationId, setActiveConversation,
    voiceEnabled, setVoiceEnabled,
  } = useChatStore()
  const { sendMessage } = useChat()
  const bottomRef = useRef<HTMLDivElement>(null)
  // 只在挂载时定一次，避免用户正聊着的时候问候语跟着时钟跳字
  const greeting = useMemo(greetingForNow, [])

  // 小人的心情完全由已有的对话状态推导，不新增任何业务状态
  const companionMood: CompanionMood =
    activeTool || (streaming && !streamingContent) ? 'thinking'
    : streaming && streamingContent ? 'happy'
    : 'idle'

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
    <div className="flex flex-col h-full">
      {/* 页头：跟其他 tab 统一的轻量页头，不再是手机 App 的渐变条 */}
      <div className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-paper-sunk shrink-0">
        <div className="flex items-center gap-3">
          <Companion mood={companionMood} size={30} animate={false} />
          <div>
            <h1 className="font-display text-2xl font-bold text-ink leading-tight">聊聊</h1>
            <p className="text-ink-soft/80 text-sm mt-0.5">我会一直陪伴着你</p>
          </div>
        </div>

        <button
          onClick={() => setVoiceEnabled(!voiceEnabled)}
          title={voiceEnabled ? '关闭语音' : '开启语音'}
          className={`w-9 h-9 flex items-center justify-center rounded-full transition-colors ${
            voiceEnabled ? 'bg-accent-50 text-accent-500' : 'text-ink-soft hover:bg-paper-sunk'
          }`}
        >
          {voiceEnabled ? (
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
            </svg>
          ) : (
            /* 4角星 sparkle — 和小人身上的火花呼应 */
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2 L13.5 10.5 L22 12 L13.5 13.5 L12 22 L10.5 13.5 L2 12 L10.5 10.5 Z"/>
            </svg>
          )}
        </button>
      </div>

      {/* 消息区：全宽面板，气泡限制在舒适阅读宽度内 */}
      <div className="flex-1 overflow-y-auto bg-paper">
        <div className="max-w-2xl mx-auto px-4 md:px-6 py-6">
          {messages.length === 0 && !streaming && (
            <div className="flex flex-col items-center mt-10">
              <div className="animate-rise-in">
                <Companion mood="idle" size={92} />
              </div>
              <p
                className="font-display text-center text-ink text-lg font-semibold mt-4 animate-rise-in"
                style={{ animationDelay: '120ms' }}
              >
                {greeting}
              </p>
              <p
                className="text-center text-ink-soft text-sm mt-1.5 animate-rise-in"
                style={{ animationDelay: '120ms' }}
              >
                想从哪儿说起都行
              </p>

              <div
                className="flex flex-wrap justify-center gap-2 mt-6 animate-rise-in"
                style={{ animationDelay: '260ms' }}
              >
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="px-3.5 py-2 rounded-full bg-paper-surface border border-paper-sunk text-sm text-ink-soft hover:text-ink hover:border-accent-300 active:scale-95 transition"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
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
              <div className="bg-paper-surface px-4 py-3 rounded-2xl rounded-tl-sm border border-paper-sunk/50">
                <span className="text-ink-soft text-sm animate-pulse">……</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* 输入区：跟消息区对齐同一舒适宽度 */}
      <div className="border-t border-paper-sunk shrink-0">
        <div className="max-w-2xl mx-auto">
          <ChatInput onSend={sendMessage} disabled={streaming} />
        </div>
      </div>
    </div>
  )
}
