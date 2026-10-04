import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/training', () => ({ getTrainingTasks: vi.fn() }))
vi.mock('@/api/history', () => ({ getHistoryApi: vi.fn() }))
vi.mock('@/api/detection', () => ({ getVideoStatusApi: vi.fn() }))

import { getVideoStatusApi } from '@/api/detection'
import { getHistoryApi } from '@/api/history'
import { getTrainingTasks } from '@/api/training'
import { useTaskStore } from '@/stores/tasks'

describe('task store recovery', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', { getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn() })
    setActivePinia(createPinia())
  })

  it('loads up to the API maximum of persisted detection tasks for recovery', async () => {
    getHistoryApi.mockResolvedValueOnce({ items: [{ id: 1, taskType: 'video', status: 'processing' }] })
    getVideoStatusApi.mockResolvedValueOnce({ status: 'processing', progress: 42 })
    const store = useTaskStore()

    await store.fetchDetectionTasks()

    expect(getHistoryApi).toHaveBeenCalledWith({ page: 1, pageSize: 100 })
    expect(getVideoStatusApi).toHaveBeenCalledWith(1)
    expect(store.detectionTasks).toEqual([{ id: 1, taskType: 'video', status: 'processing', progress: 42, errorMessage: undefined }])
  })

  it('refreshes training tasks from the server instead of relying on page-local polling', async () => {
    getTrainingTasks.mockResolvedValueOnce({ items: [{ id: 3, status: 'running' }] })
    const store = useTaskStore()

    await store.fetchTrainingTasks()

    expect(store.trainingTasks).toEqual([{ id: 3, status: 'running' }])
  })
})
