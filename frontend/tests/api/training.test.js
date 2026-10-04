import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => ({
  delete: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/utils/request', () => ({ default: request }))

import {
  downloadTrainingModel,
  downloadTrainingResults,
  deleteTrainingTask,
  exportTrainingModel,
  getTrainingMetrics,
  getTrainingStatus,
  getTrainingTasks,
  predictTrainingImage,
  startTraining,
  stopTraining,
  validateTrainingModel,
  uploadTrainingDataset,
} from '@/api/training'

describe('training api', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the six Day 6 training endpoints', async () => {
    const payload = { scene_id: 1, model_name: 'yolo11n' }

    await getTrainingTasks()
    await startTraining(payload)
    await getTrainingStatus(7)
    await getTrainingMetrics(7)
    await stopTraining(7)
    await downloadTrainingResults('task-abcd')
    await deleteTrainingTask(7)

    expect(request.get).toHaveBeenNthCalledWith(1, '/training/tasks')
    expect(request.post).toHaveBeenNthCalledWith(1, '/training/start', payload)
    expect(request.get).toHaveBeenNthCalledWith(2, '/training/status/7')
    expect(request.get).toHaveBeenNthCalledWith(3, '/training/metrics/7')
    expect(request.post).toHaveBeenNthCalledWith(2, '/training/stop/7')
    expect(request.get).toHaveBeenNthCalledWith(4, '/training/results/task-abcd', {
      responseType: 'blob',
    })
    expect(request.delete).toHaveBeenCalledWith('/training/tasks/7')
  })

  it('uses the four Day 7 evaluation endpoints', async () => {
    const validatePayload = { split: 'val', conf: 0.001, iou: 0.6 }
    const exportPayload = { version: 'v1.0.0', set_default: true }
    const formData = new FormData()

    await validateTrainingModel(9, validatePayload)
    await exportTrainingModel(9, exportPayload)
    await downloadTrainingModel(9)
    await predictTrainingImage(formData)

    expect(request.post).toHaveBeenNthCalledWith(
      1,
      '/training/validate/9',
      validatePayload,
      { timeout: 300000 },
    )
    expect(request.post).toHaveBeenNthCalledWith(2, '/training/export/9', exportPayload)
    expect(request.get).toHaveBeenCalledWith('/training/download/9', {
      responseType: 'blob',
      timeout: 120000,
    })
    expect(request.post).toHaveBeenNthCalledWith(3, '/training/predict', formData, {
      timeout: 300000,
    })
  })

  it('passes the canonical training payload through unchanged', async () => {
    const payload = {
      scene_id: 1,
      model_name: 'yolo11n.pt',
      epochs: 10,
      img_size: 64,
      batch_size: 1,
      device: 'cpu',
    }

    await startTraining(payload)

    expect(request.post).toHaveBeenCalledWith('/training/start', expect.objectContaining({
      ...payload,
      device: 'cpu',
    }))
  })

  it('sends dataset format and deterministic split options with an upload', async () => {
    const file = new File(['archive'], 'dataset.zip', { type: 'application/zip' })

    await uploadTrainingDataset(file, {
      dataset_format: 'voc',
      train_ratio: 0.7,
      val_ratio: 0.2,
      test_ratio: 0.1,
      split_seed: 19,
    })

    const formData = request.post.mock.calls[0][1]
    expect(request.post.mock.calls[0][0]).toBe('/training/datasets/upload')
    expect(formData.get('file')).toBe(file)
    expect(formData.get('dataset_format')).toBe('voc')
    expect(formData.get('train_ratio')).toBe('0.7')
    expect(formData.get('split_seed')).toBe('19')
  })
})
