import { beforeEach, describe, expect, it, vi } from 'vitest'

const userStore = {
  refreshToken: 'refresh-token',
  refreshSession: vi.fn(async () => {
    localStorage.setItem('ssdd_token', 'fresh-token')
  }),
}

vi.mock('@/stores/user', () => ({
  useUserStore: () => userStore,
}))

function streamResponse() {
  const chunks = [
    new TextEncoder().encode('data: {"type":"text_delta","content":"ok"}\n\ndata: [DONE]\n\n'),
  ]
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: vi.fn()
          .mockResolvedValueOnce({ done: false, value: chunks[0] })
          .mockResolvedValueOnce({ done: true, value: undefined }),
      }),
    },
  }
}

describe('SSE authentication recovery', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    userStore.refreshToken = 'refresh-token'
    userStore.refreshSession.mockImplementation(async () => {
      localStorage.setItem('ssdd_token', 'fresh-token')
    })
    localStorage.clear()
    localStorage.setItem('ssdd_token', 'expired-token')
  })

  it('refreshes once and reconnects with the rotated token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ error_code: 'TOKEN_EXPIRED', message: 'expired' }),
        headers: { get: () => 'request-1' },
      })
      .mockResolvedValueOnce(streamResponse())
    vi.stubGlobal('fetch', fetchMock)
    const { streamChat } = await import('@/utils/stream')
    const onDone = vi.fn()

    streamChat('/api/agent/chat/stream', { message: 'hello' }, { onDone })
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(userStore.refreshSession).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer fresh-token')
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('normalizes structured SSE errors for page consumers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"type":"error","code":"AGENT_FAILED","message":"failed"}\n\n') })
            .mockResolvedValueOnce({ done: true, value: undefined }),
        }),
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    const { streamChat } = await import('@/utils/stream')
    const onMessage = vi.fn()

    streamChat('/api/agent/chat/stream', { message: 'hello' }, { onMessage })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({
      error_code: 'AGENT_FAILED',
      status_code: 502,
      detail: { code: 'AGENT_FAILED', message: 'failed' },
      retryable: false,
    }))
  })
})
