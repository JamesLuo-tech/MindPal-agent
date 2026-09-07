import { fetchEventSource } from '@microsoft/fetch-event-source'
import { supabase } from '../lib/supabase'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) throw new Error('未登录')
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

/** 把后端返回的原始错误体（FastAPI 的 {"detail": "..."} 或纯文本）整理成能直接给用户看的一句话 */
async function extractErrorMessage(res: Response): Promise<string> {
  const raw = await res.text()
  try {
    const parsed = JSON.parse(raw)
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    // 不是 JSON，走下面的兜底文案，不把原始响应体（可能含堆栈信息）直接展示给用户
  }
  if (res.status >= 500) return '服务暂时出了点问题，请稍后再试'
  return raw && raw.length < 200 ? raw : `请求失败（${res.status}）`
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  // 204 No Content（DELETE 接口）没有响应体，解析 JSON 会直接抛错
  if (res.status === 204) {
    return undefined as T
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

export interface ActionProposalPayload {
  proposal_id: string
  action: string
  params: Record<string, unknown>
  summary: string
}

export interface ChatSSEHandlers {
  onToolUse?: (data: { tool: string; query?: string; status: string }) => void
  onToolResult?: (data: { tool: string; status: string }) => void
  onDelta?: (delta: string) => void
  onDone?: (data: { message_id: string; crisis_triggered: boolean }) => void
  onError?: (err: Error) => void
  onActionProposal?: (data: ActionProposalPayload) => void
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
          case 'tool_use':        handlers.onToolUse?.(data);        break
          case 'tool_result':     handlers.onToolResult?.(data);     break
          case 'message':         handlers.onDelta?.(data.delta);    break
          case 'action_proposal': handlers.onActionProposal?.(data); break
          case 'done':
            doneReceived = true
            handlers.onDone?.(data)
            internalAbort.abort() // 主动关闭连接，避免被当成错误
            break
          case 'error':
            doneReceived = true // 后端已 return，不会再有 done，按结束处理
            handlers.onError?.(new Error(data.message ?? data.code ?? '发生未知错误'))
            internalAbort.abort()
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

export interface ActivityTrendPoint {
  date: string
  avg_mood: number | null
  avg_energy: number | null
  avg_sleep_hours: number | null
  completed_steps: number
}

export interface WeeklyReportOut {
  period: string
  emotion_trend: EmotionTrendPoint[]
  key_events: { type: string; content: string; date: string }[]
  summary: string
  /** 后端尚未实现，接入前恒为 undefined —— 页面按"无数据"渲染空态 */
  activity_trend?: ActivityTrendPoint[]
}

export function fetchWeeklyReport() {
  return apiFetch<WeeklyReportOut>('/api/reports/weekly')
}

// ---- Today ----

export interface DailyCheckinOut {
  id: string
  checkin_date: string
  mood: number | null
  energy: number | null
  sleep_hours: number | null
  small_win: string | null
  created_at: string
}

export interface TodaySnapshotOut {
  checkin: DailyCheckinOut | null
  // 后端直接透传完整的 schedule_items 行，这里复用 ScheduleItemOut（定义见下方），
  // 前端只取用到的字段（id/title/scheduled_at）
  next_schedule_item: ScheduleItemOut | null
  recommendation: string
}

export interface CheckinUpsert {
  mood?: number | null
  energy?: number | null
  sleep_hours?: number | null
  small_win?: string | null
}

export function fetchToday() {
  return apiFetch<TodaySnapshotOut>('/api/today')
}

export function saveCheckin(payload: CheckinUpsert) {
  return apiFetch<DailyCheckinOut>('/api/today/checkin', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// ---- Small Steps / Schedule ----

export type ScheduleStatus = 'pending' | 'done' | 'skipped'

export interface ScheduleItemOut {
  id: string
  title: string
  category: string | null
  scheduled_at: string | null
  status: ScheduleStatus
  completed_at: string | null
  created_at: string
}

export interface ScheduleItemCreate {
  title: string
  category?: string
  scheduled_at?: string | null
}

export interface ScheduleItemUpdate {
  title?: string
  category?: string
  scheduled_at?: string | null
  status?: ScheduleStatus
}

export function fetchSchedule(status?: ScheduleStatus) {
  const qs = status ? `?status=${status}` : ''
  return apiFetch<ScheduleItemOut[]>(`/api/schedule${qs}`)
}

export function createScheduleItem(payload: ScheduleItemCreate) {
  return apiFetch<ScheduleItemOut>('/api/schedule', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateScheduleItem(id: string, patch: ScheduleItemUpdate) {
  return apiFetch<ScheduleItemOut>(`/api/schedule/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteScheduleItem(id: string) {
  return apiFetch<void>(`/api/schedule/${id}`, { method: 'DELETE' })
}

// ---- Support: Safety Plan ----

export interface SafetyPlanOut {
  warning_signs: string | null
  internal_coping: string | null
  distraction_people_places: string | null
  help_contacts: string | null
  professional_contacts: string | null
  safe_environment: string | null
  updated_at: string | null
}

export type SafetyPlanUpsert = Partial<Omit<SafetyPlanOut, 'updated_at'>>

export function fetchSafetyPlan() {
  return apiFetch<SafetyPlanOut | null>('/api/support/safety-plan')
}

export function saveSafetyPlan(payload: SafetyPlanUpsert) {
  return apiFetch<SafetyPlanOut>('/api/support/safety-plan', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// ---- Support: Trusted Contacts ----

export interface TrustedContactOut {
  id: string
  name: string
  relationship: string | null
  phone: string | null
  created_at: string
}

export interface TrustedContactCreate {
  name: string
  relationship?: string
  phone?: string
}

export function fetchTrustedContacts() {
  return apiFetch<TrustedContactOut[]>('/api/support/contacts')
}

export function createTrustedContact(payload: TrustedContactCreate) {
  return apiFetch<TrustedContactOut>('/api/support/contacts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteTrustedContact(id: string) {
  return apiFetch<void>(`/api/support/contacts/${id}`, { method: 'DELETE' })
}

// ---- Chat Actions（确认后才真正落库的写入动作）----

export interface ActionConfirmResult {
  action: string
  result: Record<string, unknown>
}

/** 用户在确认卡片上点了"确认"后调用——真正的数据库写入只在这一步发生 */
export function confirmAction(action: string, params: Record<string, unknown>) {
  return apiFetch<ActionConfirmResult>('/api/chat/actions/confirm', {
    method: 'POST',
    body: JSON.stringify({ action, params }),
  })
}

// ---- Appointment Summary（问诊摘要）----

export interface AppointmentSummaryOut {
  period: string
  bullets: string[]
  discuss_topics: string | null
  generated_at: string
}

export function fetchAppointmentSummary(days: number, discussTopics?: string) {
  return apiFetch<AppointmentSummaryOut>('/api/reports/appointment-summary', {
    method: 'POST',
    body: JSON.stringify({ days, discuss_topics: discussTopics || null }),
  })
}

/** 返回正式报告样式的 PDF 二进制内容——跟 apiFetch 不一样，响应体不是 JSON，
 * 不能走 apiFetch<T>()（它内部固定调用 res.json()）。 */
export async function fetchAppointmentSummaryPdf(days: number, discussTopics?: string): Promise<Blob> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${BASE_URL}/api/reports/appointment-summary/pdf`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ days, discuss_topics: discussTopics || null }),
  })
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res))
  }
  return res.blob()
}
