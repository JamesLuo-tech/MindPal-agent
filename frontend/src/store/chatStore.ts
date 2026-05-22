import { create } from 'zustand'
import type { User } from '@supabase/supabase-js'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: Date
}

export interface Conversation {
  id: string
  title: string | null
  createdAt: Date
}

export interface ActiveTool {
  tool: string
  status: 'searching' | 'done'
}

// ---- Auth Store ----
interface AuthState {
  user: User | null
  setUser: (user: User | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
}))

// ---- Chat Store ----
interface ChatState {
  conversations: Conversation[]
  activeConversationId: string | null
  messages: Message[]
  streaming: boolean
  streamingContent: string
  activeTool: ActiveTool | null
  voiceEnabled: boolean

  setConversations: (convs: Conversation[]) => void
  setActiveConversation: (id: string) => void
  setMessages: (msgs: Message[]) => void
  appendMessage: (msg: Message) => void
  setStreaming: (v: boolean) => void
  appendStreamDelta: (delta: string) => void
  commitStreamedMessage: (messageId: string, crisisTriggered: boolean) => void
  setActiveTool: (tool: ActiveTool | null) => void
  setVoiceEnabled: (v: boolean) => void
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  activeConversationId: null,
  messages: [],
  streaming: false,
  streamingContent: '',
  activeTool: null,
  voiceEnabled: false,

  setConversations: (conversations) => set({ conversations }),
  setActiveConversation: (id) =>
    set({ activeConversationId: id, messages: [], streamingContent: '', activeTool: null }),
  setMessages: (messages) => set({ messages }),
  appendMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setStreaming: (streaming) => set({ streaming, streamingContent: streaming ? '' : '' }),
  appendStreamDelta: (delta) => set((s) => ({ streamingContent: s.streamingContent + delta })),
  commitStreamedMessage: (messageId, _crisisTriggered) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: messageId,
          role: 'assistant',
          content: s.streamingContent,
          createdAt: new Date(),
        },
      ],
      streaming: false,
      streamingContent: '',
      activeTool: null,
    })),
  setActiveTool: (activeTool) => set({ activeTool }),
  setVoiceEnabled: (voiceEnabled) => set({ voiceEnabled }),
}))
