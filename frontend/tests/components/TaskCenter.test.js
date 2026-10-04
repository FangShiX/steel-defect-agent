import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/components/common/TaskCenter.vue'), 'utf8')

describe('TaskCenter behavior contract', () => {
  it('keeps three recent completed tasks and supports task-group read actions', () => {
    expect(source).toContain(".slice(0, 3)")
    expect(source).toContain('function markTaskGroupRead(tasks)')
    expect(source).toContain("['failed', 'completed'].includes(group.key)")
  })

  it('stops close-button clicks from opening task or notification details', () => {
    expect(source).toContain('@click.stop="closeNotification(item)"')
    expect(source).toContain('@click.stop="closeTask(task)"')
  })

  it('localizes completed detection messages in Chinese', () => {
    expect(source).toContain('检测到 ${detectionCompleted[2]} 个目标。')
  })
})
