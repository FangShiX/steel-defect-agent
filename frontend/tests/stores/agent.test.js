import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/agent', () => ({
  archiveAgentSession: vi.fn(),
  cancelAgentRunApi: vi.fn(),
  cancelAgentToolApi: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentArtifact: vi.fn(),
  getAgentMessageImage: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentSessions: vi.fn().mockResolvedValue([]),
  renameAgentSession: vi.fn(),
}))

import { getAgentArtifact, getAgentSession, listAgentSessions } from '@/api/agent'
import { useAgentStore } from '@/stores/agent'

describe('agent store user isolation', () => {
  beforeEach(() => {
    const values = new Map()
    vi.stubGlobal('localStorage', {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key),
      clear: () => values.clear(),
    })
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('keeps each user current session and cached list in a separate namespace', () => {
    const store = useAgentStore()

    store.activateUser(1)
    store.currentSessionId = 'user-1-session'
    store.addMessage({ role: 'user', content: 'user one' })

    expect(localStorage.getItem('ssdd_agent_session:1')).toBe('user-1-session')
    expect(localStorage.getItem('ssdd_agent_sessions:1')).toContain('user-1-session')

    store.activateUser(2)
    expect(store.userScope).toBe('2')
    expect(store.currentSessionId).not.toBe('user-1-session')
    expect(store.messages).toEqual([])
    expect(store.sessions).toEqual([])

    store.currentSessionId = 'user-2-session'
    store.addMessage({ role: 'user', content: 'user two' })
    store.activateUser(1)

    expect(store.currentSessionId).toBe('user-1-session')
    expect(store.sessions[0].id).toBe('user-1-session')
    expect(localStorage.getItem('ssdd_agent_session:2')).toBe('user-2-session')
  })

  it('drops in-memory chat state on logout without deleting persisted user scope', () => {
    const store = useAgentStore()
    store.activateUser(7)
    store.currentSessionId = 'persistent-session'
    store.addMessage({ role: 'user', content: 'persist me' })

    store.clearUserScope()

    expect(store.userScope).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.sessions).toEqual([])
    expect(localStorage.getItem('ssdd_agent_session:7')).toBe('persistent-session')
  })

  it('keeps session owner metadata returned for an administrator', async () => {
    listAgentSessions.mockResolvedValueOnce([{
      id: 'other-user-session',
      owner_id: 9,
      owner_username: 'other-user',
      title: 'persisted chat',
    }])
    const store = useAgentStore()

    await store.fetchSessions(1)

    expect(store.sessions[0]).toMatchObject({
      id: 'other-user-session',
      ownerId: 9,
      ownerUsername: 'other-user',
    })
  })

  it('marks a partially streamed reply as cancelled when the user stops it', () => {
    const store = useAgentStore()
    const abort = vi.fn()
    store.activateUser(1)
    store.addMessage({ role: 'user', content: 'start' })
    store.addMessage({ role: 'assistant', content: 'partial', status: 'streaming' })
    store.isStreaming = true
    store.abortController = abort

    store.stopStreaming()

    expect(abort).toHaveBeenCalledTimes(1)
    expect(store.messages.at(-1).status).toBe('cancelled')
    expect(store.connectionStatus).toBe('idle')
  })

  it('restores statistics, history, and knowledge cards from persisted tool calls', async () => {
    listAgentSessions.mockResolvedValueOnce([{ id: 'card-session', title: 'cards' }])
    getAgentSession.mockResolvedValueOnce({
      title: 'cards',
      messages: [{
        id: 1,
        role: 'assistant',
        content: '已查询',
        tool_calls: [
          { id: 'stats', card_type: 'statistics', status: 'success', result: JSON.stringify({ total_tasks: 2, total_images: 3, total_objects: 4 }) },
          { id: 'history', card_type: 'history', status: 'success', result: JSON.stringify({ tasks: [{ id: 8, status: 'completed' }] }) },
          { id: 'rag', card_type: 'knowledge_citations', status: 'success', result: JSON.stringify({ found: true, results: [{ document_title: '手册', content: '内容' }] }) },
        ],
      }],
    })
    const store = useAgentStore()

    await store.fetchSessions(1)
    await store.loadSession('card-session')

    expect(store.messages[0].toolResultCards).toEqual([
      expect.objectContaining({ type: 'statistics', result: expect.objectContaining({ total_tasks: 2 }) }),
      expect.objectContaining({ type: 'history', result: expect.objectContaining({ tasks: [{ id: 8, status: 'completed' }] }) }),
      expect.objectContaining({ type: 'knowledge_citations', result: expect.objectContaining({ found: true }) }),
    ])
  })

  it('hydrates protected Agent artifact URLs with authenticated blobs', async () => {
    const blob = new Blob(['image'], { type: 'image/jpeg' })
    getAgentArtifact.mockResolvedValueOnce(blob)
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:agent-artifact')
    const store = useAgentStore()
    const message = { detectionResult: { annotatedImageUrl: '/api/agent/artifacts/annotated_example.jpg' } }

    await store.hydrateDetectionImages(message)

    expect(getAgentArtifact).toHaveBeenCalledWith('annotated_example.jpg')
    expect(message.detectionResult.annotatedImageUrl).toBe('blob:agent-artifact')
    createObjectURL.mockRestore()
  })
})
