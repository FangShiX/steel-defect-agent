import { useUserStore } from '@/stores/user'

export function streamChat(url, body, callbacks = {}, options = {}) {
  const { onMessage, onDone, onError, onRetry } = callbacks
  const {
    maxRetries = 1,
    retryDelay = 800,
  } = options
  const controller = new AbortController()
  const isFormData = body instanceof FormData
  let retryCount = 0
  let settled = false
  let receivedAnyMessage = false
  let tokenRefreshAttempted = false

  async function connect() {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
          ...(localStorage.getItem('ssdd_token') ? { Authorization: `Bearer ${localStorage.getItem('ssdd_token')}` } : {}),
        },
        body: isFormData ? body : JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) {
        let payload = null
        try { payload = await response.json() } catch { /* non-JSON gateway response */ }
        const error = new Error(payload?.message || payload?.detail?.message || `HTTP ${response.status}`)
        error.code = payload?.error_code || payload?.detail?.code || `HTTP_${response.status}`
        error.statusCode = payload?.status_code || response.status
        error.detail = payload?.detail
        error.requestId = payload?.request_id || response.headers.get('x-request-id')
        error.retryable = payload?.retryable ?? [408, 425, 429, 500, 502, 503, 504].includes(response.status)
        if (response.status === 401 && !tokenRefreshAttempted) {
          const userStore = useUserStore()
          if (userStore.refreshToken) {
            tokenRefreshAttempted = true
            try {
              await userStore.refreshSession()
              return connect()
            } catch { /* fall through to the normal auth error */ }
          }
        }
        throw error
      }
      if (!response.body) throw new Error('当前浏览器不支持流式响应')

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (!settled) {
        const { done, value } = await reader.read()
        if (done) {
          processSSEMessage(buffer, onMessage)
          settled = true
          onDone?.()
          return
        }

        buffer += decoder.decode(value, { stream: true })
        const messages = buffer.split(/\r?\n\r?\n/)
        buffer = messages.pop() || ''

        for (const message of messages) {
          if (!message.trim()) continue
          const shouldStop = processSSEMessage(message, (event) => {
            receivedAnyMessage = true
            onMessage?.(event)
          })
          if (shouldStop) {
            settled = true
            onDone?.()
            return
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return

      const canRetry = !receivedAnyMessage && Boolean(err.retryable ?? !err.code) && retryCount < maxRetries
      if (canRetry) {
        retryCount += 1
        onRetry?.({ retryCount, error: err })
        window.setTimeout(connect, retryDelay * retryCount)
        return
      }

      settled = true
      onError?.(err)
    }
  }

  connect()

  return () => {
    settled = true
    controller.abort()
  }
}

function processSSEMessage(message, onMessage) {
  if (!message.trim()) return false

  const lines = message.split(/\r?\n/)
  const dataLines = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())

  if (!dataLines.length) return false

  const data = dataLines.join('\n')
  if (data === '[DONE]') return true

  try {
    const event = JSON.parse(data)
    if (event?.type === 'error') {
      event.error_code ||= event.code || 'SSE_ERROR'
      event.code ||= event.error_code
      event.status_code ||= 502
      event.detail ||= { code: event.error_code, message: event.message || 'SSE request failed' }
      event.retryable = Boolean(event.retryable)
    }
    onMessage?.(event)
  } catch {
            onMessage?.({ type: 'text_delta', content: data })
  }

  return false
}
