import { useRef } from 'react'
import { useChatStore } from '../store/chatStore'
import { streamChat, speakText } from '../api/client'

export function useChat() {
  const store = useChatStore()
  const abortRef = useRef<AbortController | null>(null)

  async function sendMessage(content: string) {
    const convId = store.activeConversationId
    if (!convId || store.streaming) return

    store.appendMessage({
      id: crypto.randomUUID(),
      role: 'user',
      content,
      createdAt: new Date(),
    })
    store.setStreaming(true)

    abortRef.current = new AbortController()

    await streamChat(
      convId,
      content,
      {
        onToolUse: (d) => {
          store.setActiveTool({ tool: d.tool, status: 'searching' })
        },
        onToolResult: (d) => {
          store.setActiveTool({ tool: d.tool, status: 'done' })
          // 短暂显示"完成"后清除
          setTimeout(() => store.setActiveTool(null), 1200)
        },
        onDelta: (delta) => store.appendStreamDelta(delta),
        onDone: (d) => {
          // 用 getState() 取最新值，避免闭包拿到旧快照
          const { streamingContent, voiceEnabled, commitStreamedMessage } = useChatStore.getState()
          commitStreamedMessage(d.message_id, d.crisis_triggered)
          if (voiceEnabled && streamingContent) {
            speakText(streamingContent).catch(() => {})
          }
        },
        onError: (err) => {
          store.setStreaming(false)
          store.appendMessage({
            id: crypto.randomUUID(),
            role: 'assistant',
            content: err.message || '出错了，请稍后再试',
            createdAt: new Date(),
          })
        },
      },
      abortRef.current.signal,
    )
  }

  function stopStreaming() {
    abortRef.current?.abort()
    store.setStreaming(false)
  }

  return { sendMessage, stopStreaming }
}
