import { fetchEventSource } from '@microsoft/fetch-event-source'
import { supabase } from '../lib/supabase'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) throw new Error('未登录')
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err)
  }
  return res.json()
}

// ---- Conversations ----

export interface ConversationOut {
  id: string
  title: string | null
  created_at: string
}

export function listConversations() {
  return apiFetch<ConversationOut[]>('/api/conversations')
}

export function createConversation(title?: string) {
  return apiFetch<ConversationOut>('/api/conversations', {
    method: 'POST',
    body: JSON.stringify({ title: title ?? null }),
  })
}

// ---- Chat SSE ----

export interface ChatSSEHandlers {
  onToolUse?: (data: { tool: string; query?: string; status: string }) => void
  onToolResult?: (data: { tool: string; source: string; status: string }) => void
  onDelta?: (delta: string) => void
  onDone?: (data: { message_id: string; crisis_triggered: boolean }) => void
  onError?: (err: Error) => void
}

export async function streamChat(
  conversationId: string,
  message: string,
  handlers: ChatSSEHandlers,
  signal?: AbortSignal,
) {
  const headers = await getAuthHeaders()
  const internalAbort = new AbortController()
  let doneReceived = false

  // 合并外部 signal（用于手动中断）和内部 signal（done 后自动关闭）
  signal?.addEventListener('abort', () => internalAbort.abort())

  try {
    await fetchEventSource(`${BASE_URL}/api/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ conversation_id: conversationId, message }),
      signal: internalAbort.signal,
      onmessage(ev) {
        const data = JSON.parse(ev.data)
        switch (ev.event) {
          case 'tool_use':    handlers.onToolUse?.(data);    break
          case 'tool_result': handlers.onToolResult?.(data); break
          case 'message':     handlers.onDelta?.(data.delta); break
          case 'done':
            doneReceived = true
            handlers.onDone?.(data)
            internalAbort.abort() // 主动关闭连接，避免被当成错误
            break
        }
      },
      onerror(err) {
        if (doneReceived) return         // done 后的关闭是正常的，忽略
        if ((err as Error).name === 'AbortError') return
        handlers.onError?.(err)
        throw err
      },
    })
  } catch (err) {
    // done 已收到时的任何后续异常都属于正常关闭，忽略
    if (!doneReceived) throw err
  }
}

// ---- TTS ----

export async function speakText(text: string): Promise<void> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${BASE_URL}/api/tts`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error('TTS failed')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.onended = () => URL.revokeObjectURL(url)
  await audio.play()
}

// ---- Emotions ----

export interface EmotionOut {
  id: string
  primary_emotion: string | null
  secondary_emotions: string[]
  intensity: number | null
  triggers: string[]
  created_at: string
}

export function fetchEmotions(days = 30) {
  return apiFetch<EmotionOut[]>(`/api/emotions?days=${days}`)
}

// ---- Weekly Report ----

export interface EmotionTrendPoint {
  date: string
  avg_intensity: number
  dominant_emotion: string
  count: number
}

export interface WeeklyReportOut {
  period: string
  emotion_trend: EmotionTrendPoint[]
  key_events: { type: string; content: string; date: string }[]
  summary: string
}

export function fetchWeeklyReport() {
  return apiFetch<WeeklyReportOut>('/api/reports/weekly')
}
