import { describe, expect, it } from 'vitest'
import {
  buildAgentCard,
  normalizeAgentEvent,
  normalizeDetectionResult,
  restoreMessageCards,
} from '@/utils/agentCards'

describe('agent card normalization', () => {
  it('normalizes alternate stream event names and payloads', () => {
    expect(normalizeAgentEvent({ event: 'tool_call_result', tool: 'detect_single', output: '{"total_objects": 2}' })).toMatchObject({
      type: 'tool_result',
      tool_name: 'detect_single',
      result: { total_objects: 2 },
    })
  })

  it('normalizes single and batch detection result shapes', () => {
    expect(normalizeDetectionResult({ task_id: 7, detections: [{ class_name: 'scratch', confidence: 0.8 }] })).toMatchObject({
      taskId: 7,
      totalObjects: 1,
      objects: [{ className: 'scratch', confidence: 0.8 }],
    })
    expect(normalizeDetectionResult({ results: [{ filename: 'a.jpg', detections: [] }] })).toMatchObject({
      totalImages: 1,
      items: [{ fileName: 'a.jpg', totalObjects: 0 }],
    })
  })

  it('restores persisted cards without duplicating detection cards', () => {
    const message = restoreMessageCards({
      toolCalls: [{ id: 'stats', name: 'get_detection_statistics', status: 'success', result: { total_tasks: 3 } }],
      cards: [{ id: 'knowledge', type: 'knowledge_citations', result: { citations: [{ title: 'doc' }] } }],
    })
    expect(message.toolResultCards).toHaveLength(2)
    expect(message.toolResultCards.map((card) => card.type)).toEqual(expect.arrayContaining(['statistics', 'knowledge_citations']))
  })

  it('preserves references and status when building a card', () => {
    expect(buildAgentCard({ toolName: 'query_detection_history', result: { tasks: [] }, status: 'success', meta: { id: 'history-1' } })).toMatchObject({
      id: 'history-1',
      type: 'history',
      status: 'success',
    })
  })
})
