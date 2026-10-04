import { describe, expect, it } from 'vitest'
import { buildTaskCenterItems, filterTaskCenterItems, hasActiveTasks } from '@/utils/taskCenter'

describe('task center utilities', () => {
  const items = buildTaskCenterItems({
    trainingTasks: [{
      taskId: 8,
      taskName: 'baseline training',
      sceneName: 'steel',
      modelName: 'YOLO11n',
      status: 'running',
      currentEpoch: 5,
      totalEpochs: 10,
      createdAt: '2026-07-20T10:00:00Z',
    }],
    detectionTasks: [{
      id: 9,
      taskType: 'video',
      sceneName: 'steel',
      status: 'completed',
      progress: 87,
      createdAt: '2026-07-20T11:00:00Z',
    }],
  })

  it('merges real training and detection tasks in reverse chronological order', () => {
    expect(items.map((item) => item.key)).toEqual(['detection-9', 'training-8'])
    expect(items[1].progress).toBe(50)
    expect(items[0].progress).toBe(100)
  })

  it('filters by category, status and keyword', () => {
    expect(filterTaskCenterItems(items, { category: 'training' })).toHaveLength(1)
    expect(filterTaskCenterItems(items, { status: 'completed' })[0].id).toBe(9)
    expect(filterTaskCenterItems(items, { keyword: 'YOLO11n' })[0].id).toBe(8)
  })

  it('detects tasks that require automatic refresh', () => {
    expect(hasActiveTasks(items)).toBe(true)
    expect(hasActiveTasks(items.filter((item) => item.status === 'completed'))).toBe(false)
  })
})
