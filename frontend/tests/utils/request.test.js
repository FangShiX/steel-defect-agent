import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('request utility', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('creates the axios instance with expected defaults', async () => {
    const { default: request } = await import('@/utils/request')

    expect(request).toBeDefined()
    expect(request.defaults.baseURL).toBe('/api')
    expect(request.defaults.timeout).toBe(30000)
    expect(request.defaults.headers['Content-Type']).toBe('application/json')
  })
})

describe('error reporter', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('stores frontend error information locally', async () => {
    const { reportError, ERROR_LOG_STORAGE_KEY } = await import('@/utils/errorReporter')

    const entry = reportError(new Error('test error'), { type: 'test_error' })
    const stored = JSON.parse(localStorage.getItem(ERROR_LOG_STORAGE_KEY))

    expect(entry.type).toBe('test_error')
    expect(stored).toHaveLength(1)
    expect(stored[0].message).toBe('test error')
  })

  it('installs a Vue error handler', async () => {
    const { setupErrorReporting } = await import('@/utils/errorReporter')
    const app = { config: {} }

    setupErrorReporting(app)

    expect(typeof app.config.errorHandler).toBe('function')
  })
})
