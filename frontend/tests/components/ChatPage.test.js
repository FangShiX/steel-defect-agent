import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, expect, it } from 'vitest'

describe('ChatPage integration', () => {
  it('renders the chat page with agent store and message list', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/views/ChatPage.vue'), 'utf8')

    expect(page).toContain("import { useAgentStore } from '@/stores/agent'")
    expect(page).toContain("import MessageList from '@/components/agent/MessageList.vue'")
    expect(page).toContain('<MessageList')
  })

  it('keeps the stream stop action and sends the selected model', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/views/ChatPage.vue'), 'utf8')

    expect(page).toContain('agentStore.stopStreaming()')
    expect(page).toContain("formData.append('model', model.value)")
  })

  it('resolves the default detection model and locks the shortcut while it runs', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/views/ChatPage.vue'), 'utf8')

    expect(page).toContain("import { getModelsApi, getScenesApi } from '@/api/models'")
    expect(page).toContain('return { ...quickDetectOptions, modelId: model.id }')
    expect(page).toContain('isQuickDetecting.value = true')
    expect(page).toContain(':disabled="agentStore.isStreaming || isQuickDetecting"')
  })

  it('sends the user message without exposing a client-side context prompt', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/views/ChatPage.vue'), 'utf8')

    expect(page).toContain("formData.append('message', text)")
    expect(page).not.toContain('buildContextualMessage')
    expect(page).not.toContain('[前端上下文]')
  })
})
