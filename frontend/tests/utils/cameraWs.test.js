import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/stores/user', () => ({ useUserStore: () => ({ token: 'test-token' }) }))

import { createCameraWs } from '@/utils/cameraWs'

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.CONNECTING
    FakeWebSocket.instances.push(this)
  }

  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3 })
  addEventListener = vi.fn()
}

describe('camera WebSocket reconnect lifecycle', () => {
  afterEach(() => {
    FakeWebSocket.instances = []
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('reports each reconnect and releases control to the caller after the retry limit', () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const reconnect = vi.fn()
    const failed = vi.fn()
    const client = createCameraWs({ modelId: 1, onReconnect: reconnect, onReconnectFailed: failed })

    client.connect()
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      FakeWebSocket.instances.at(-1).onclose({ code: 1006 })
      expect(reconnect).toHaveBeenLastCalledWith(attempt, 3)
      vi.advanceTimersByTime(500 * attempt)
    }
    FakeWebSocket.instances.at(-1).onclose({ code: 1006 })

    expect(failed).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect after an explicit close', () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const reconnect = vi.fn()
    const client = createCameraWs({ modelId: 1, onReconnect: reconnect })

    client.connect()
    client.close()
    FakeWebSocket.instances[0].onclose({ code: 1000 })
    vi.runAllTimers()

    expect(reconnect).not.toHaveBeenCalled()
  })
})
