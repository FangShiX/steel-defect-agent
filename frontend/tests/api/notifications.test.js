import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/utils/request', () => ({ default: request }))

import { listNotificationsApi, markAllNotificationsReadApi, markNotificationReadApi } from '@/api/notifications'

describe('notifications api', () => {
  beforeEach(() => vi.clearAllMocks())

  it('supports listing, single-read, and bulk-read actions', async () => {
    await listNotificationsApi({ limit: 100, unread_only: false })
    await markNotificationReadApi(7)
    await markAllNotificationsReadApi()

    expect(request.get).toHaveBeenCalledWith('/notifications', { params: { limit: 100, unread_only: false } })
    expect(request.post).toHaveBeenNthCalledWith(1, '/notifications/7/read')
    expect(request.post).toHaveBeenNthCalledWith(2, '/notifications/read-all')
  })
})
