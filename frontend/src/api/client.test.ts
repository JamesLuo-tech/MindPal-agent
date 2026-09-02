import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiFetch } from './client'
import { supabase } from '../lib/supabase'

vi.mock('../lib/supabase', () => ({
  supabase: { auth: { getSession: vi.fn() } },
}))

beforeEach(() => {
  vi.mocked(supabase.auth.getSession).mockResolvedValue({
    data: { session: { access_token: 'fake-token' } as any },
    error: null,
  } as any)
})

describe('apiFetch', () => {
  it('parses a JSON response body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ))

    const result = await apiFetch<{ ok: boolean }>('/api/whatever')
    expect(result).toEqual({ ok: true })
  })

  it('does not try to parse a body on 204 No Content (DELETE endpoints)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    // 回归用例：之前这里会因为对空 body 调 res.json() 抛
    // "Failed to execute 'json' on 'Response': Unexpected end of JSON input"
    await expect(apiFetch<void>('/api/schedule/some-id', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('throws with the response body text when the request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('Schedule item not found', { status: 404 }),
    ))

    await expect(apiFetch('/api/schedule/missing')).rejects.toThrow('Schedule item not found')
  })

  it('extracts FastAPI\'s {"detail": "..."} shape instead of showing raw JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not your schedule item' }), { status: 403 }),
    ))

    await expect(apiFetch('/api/schedule/x')).rejects.toThrow('Not your schedule item')
  })

  it('shows a friendly fallback instead of a raw response body for 5xx errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('Internal Server Error', { status: 500 }),
    ))

    await expect(apiFetch('/api/today')).rejects.toThrow('服务暂时出了点问题，请稍后再试')
  })
})
