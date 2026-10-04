import { defineStore } from 'pinia'
import {
  archiveAgentSession,
  cancelAgentRunApi,
  cancelAgentToolApi,
  deleteAgentSession,
  getAgentArtifact,
  getAgentMessageAttachment,
  getAgentMessageImage,
  getAgentSession,
  listAgentSessions,
  renameAgentSession,
} from '@/api/agent'
import {
  buildAgentCard,
  normalizeDetectionResult,
  restoreMessageCards,
} from '@/utils/agentCards'

const SESSION_KEY = 'ssdd_agent_session'
const SESSIONS_KEY = 'ssdd_agent_sessions'
const USER_KEY = 'ssdd_user'

function storageKey(base, userId) {
  return `${base}:${userId}`
}

function storedUserId() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')?.id ?? null
  } catch {
    return null
  }
}

function loadSavedSessions(userId) {
  if (userId == null) return []
  try {
    return JSON.parse(localStorage.getItem(storageKey(SESSIONS_KEY, userId)) || '[]')
  } catch {
    return []
  }
}

function initialState() {
  const userId = storedUserId()
  return {
    userScope: userId == null ? null : String(userId),
    currentSessionId: userId == null
      ? crypto.randomUUID()
      : localStorage.getItem(storageKey(SESSION_KEY, userId)) || crypto.randomUUID(),
    sessions: loadSavedSessions(userId),
  }
}

function serializeMessage(message) {
  const {
    imagePreviewUrls,
    detectionPreviewUrl,
    ...serializable
  } = message
  return serializable
}

const AGENT_LABEL_BY_NAME = {
  detection: '检测 Agent',
  data: '数据 Agent',
  general: '通用 Agent',
  training: '训练 Agent',
}

export const AGENT_ICON_BY_NAME = {
  detection: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`,
  data: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="12" width="3" height="9" rx="1"/><rect x="10" y="7" width="3" height="14" rx="1"/><rect x="17" y="3" width="3" height="18" rx="1"/></svg>`,
  general: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  training: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 4 4 4-4 4"/><path d="M14 4h4"/><path d="M14 8h4"/><path d="M14 12h4"/><path d="M6 16h12"/><path d="M6 20h12"/></svg>`,
}

function ensureAgentLabel(tool) {
  if (tool.agentLabel) return
  tool.agentLabel = AGENT_LABEL_BY_NAME[tool.agent] || ''
}

  function artifactFilename(url) {
    if (typeof url !== 'string' || !url) return ''
    try {
      const parsed = new URL(url, window.location.origin)
      const match = parsed.pathname.match(/^\/api\/agent\/artifacts\/([^/?]+)$/)
      return match ? decodeURIComponent(match[1]) : ''
    } catch {
      return ''
    }
  }

async function hydrateArtifactUrl(url) {
  const filename = artifactFilename(url)
  if (!filename) return url || ''
  try {
    return URL.createObjectURL(await getAgentArtifact(filename))
  } catch {
    return ''
  }
}

export const useAgentStore = defineStore('agent', {
  state: () => ({
    ...initialState(),
    messages: [],
    isStreaming: false,
    abortController: null,
    selectedImages: [],
    imagePreviewUrls: [],
    currentToolCall: null,
    errorMessage: '',
    connectionStatus: 'idle',
    reconnectCount: 0,
    activeRunId: '',
    lastRestoreError: '',
    sessionsLoading: false,
    sessionSearch: '',
    sessionPage: 1,
    sessionPageSize: 20,
    sessionTotal: 0,
    showArchived: false,
  }),

  getters: {
    messageCount: (state) => state.messages.length,
    hasMessages: (state) => state.messages.length > 0,
  },

  actions: {
    activateUser(userId = storedUserId()) {
      const nextScope = userId == null ? null : String(userId)
      if (this.userScope === nextScope) return
      this.stopStreaming()
      this.clearImages()
      this.messages = []
      this.currentToolCall = null
      this.errorMessage = ''
      this.userScope = nextScope
      this.sessions = loadSavedSessions(nextScope)
      this.currentSessionId = nextScope == null
        ? crypto.randomUUID()
        : localStorage.getItem(storageKey(SESSION_KEY, nextScope)) || crypto.randomUUID()
    },

    clearUserScope() {
      this.activateUser(null)
    },

    persistCurrentSessionId() {
      if (this.userScope != null) {
        localStorage.setItem(storageKey(SESSION_KEY, this.userScope), this.currentSessionId)
      }
    },

    async fetchSessions(userIdOrOptions = storedUserId()) {
      const options = typeof userIdOrOptions === 'object' && userIdOrOptions !== null ? userIdOrOptions : {}
      const userId = typeof userIdOrOptions === 'object' && userIdOrOptions !== null
        ? (options.userId ?? storedUserId())
        : userIdOrOptions
      this.activateUser(userId)
      this.sessionsLoading = true
      const params = {
        search: (options.search ?? this.sessionSearch) || undefined,
        page: options.page ?? this.sessionPage,
        page_size: options.pageSize ?? this.sessionPageSize,
        archived: options.archived ?? this.showArchived,
      }
      try {
        const response = await listAgentSessions(params)
        const sessions = Array.isArray(response) ? response : (response.items || response.sessions || [])
        this.sessionTotal = response.total ?? response.count ?? sessions.length
        this.sessionPage = params.page || 1
        this.sessionPageSize = params.page_size || 20
        const nextSessions = sessions.map((session) => ({
          id: session.id,
        ownerId: session.owner_id,
        ownerUsername: session.owner_username,
        title: session.title,
          archived: Boolean(session.archived),
        createdAt: session.created_at,
        updatedAt: session.updated_at,
        messages: [],
        }))
        this.sessions = options.append
          ? [...this.sessions, ...nextSessions.filter((session) => !this.sessions.some((item) => item.id === session.id))]
          : nextSessions
        if (this.sessions.some((session) => session.id === this.currentSessionId)) {
          await this.loadSession(this.currentSessionId)
        } else {
          this.messages = []
          this.currentSessionId = crypto.randomUUID()
          this.persistCurrentSessionId()
        }
      } finally {
        this.sessionsLoading = false
      }
    },

    addMessage(message) {
      this.persistCurrentSessionId()
      this.messages.push({
        id: crypto.randomUUID(),
        createdAt: new Date().toISOString(),
        status: 'done',
        ...message,
      })
      this.saveSession()
    },

    appendAssistantContent(content) {
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg?.role === 'assistant') {
        lastMsg.content += content
        lastMsg.status = this.isStreaming ? 'streaming' : 'done'
        this.saveSession()
      }
    },

    setToolCall(toolCall) {
      this.currentToolCall = toolCall
      const lastAssistant = [...this.messages].reverse().find((message) => message.role === 'assistant')
      if (lastAssistant) {
        lastAssistant.toolCalls = lastAssistant.toolCalls || []
        const key = toolCall.id || toolCall.name || toolCall.tool_name || 'tool'
        const existingIndex = lastAssistant.toolCalls.findIndex((item) => (
          (item.id || item.name || item.tool_name || 'tool') === key
        ))
        if (existingIndex >= 0) {
          lastAssistant.toolCalls[existingIndex] = {
            ...lastAssistant.toolCalls[existingIndex],
            ...toolCall,
            updatedAt: new Date().toISOString(),
          }
        } else {
          lastAssistant.toolCalls.push({
            ...toolCall,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          })
        }
        this.saveSession()
      }
    },

    addToolResultCard(result, toolName = '', meta = {}) {
      const assistantMessage = [...this.messages].reverse().find((message) => message.role === 'assistant')
      if (!assistantMessage) return null
      const card = buildAgentCard({
        toolName,
        result,
        status: meta.status || 'success',
        meta,
        displayOrder: (assistantMessage.toolResultCards?.length || 0) + 1,
      })
      if (card.type === 'detection_result') {
        assistantMessage.detectionResult = normalizeDetectionResult(card.result, card)
        const userMessage = [...this.messages].reverse().find((message) => message.role === 'user')
        assistantMessage.detectionPreviewUrl = userMessage?.imagePreviewUrls?.[0] || assistantMessage.detectionPreviewUrl || ''
        void this.hydrateDetectionImages(assistantMessage)
      } else {
        assistantMessage.toolResultCards = assistantMessage.toolResultCards || []
        assistantMessage.toolResultCards.push(card)
      }
      this.saveSession()
      return card
    },

    setConnectionStatus(status) {
      this.connectionStatus = status
    },

    markLastAssistantError(message) {
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg?.role === 'assistant') {
        lastMsg.status = 'error'
        lastMsg.errorMessage = message
        if (!lastMsg.content) {
          lastMsg.content = message || '智能体响应失败，请稍后重试。'
        }
      }
      this.errorMessage = message || ''
      this.saveSession()
    },

    addSelectedImages(files) {
      files.forEach(file => {
        this.selectedImages.push(file)
        this.imagePreviewUrls.push(URL.createObjectURL(file))
      })
    },

    removeSelectedImage(index) {
      if (this.imagePreviewUrls[index]) URL.revokeObjectURL(this.imagePreviewUrls[index])
      this.selectedImages.splice(index, 1)
      this.imagePreviewUrls.splice(index, 1)
    },

    clearImages() {
      this.imagePreviewUrls.forEach(url => URL.revokeObjectURL(url))
      this.selectedImages = []
      this.imagePreviewUrls = []
    },

    stopStreaming() {
      const wasStreaming = this.isStreaming
      this.abortController?.()
      this.abortController = null
      this.isStreaming = false
      this.connectionStatus = 'idle'
      const lastMessage = this.messages[this.messages.length - 1]
      if (wasStreaming && lastMessage?.role === 'assistant' && lastMessage.status === 'streaming') {
        lastMessage.status = 'cancelled'
        lastMessage.errorMessage = '请求已取消'
        this.saveSession()
      }
    },

    async cancelCurrentRun() {
      const runId = this.activeRunId || this.currentSessionId
      this.stopStreaming()
      if (!runId) return
      try {
        await cancelAgentRunApi(runId)
      } catch {
        // Backend may not support remote cancellation yet; local SSE cancellation is still applied.
      }
    },

    async cancelCurrentTool() {
      const runId = this.activeRunId || this.currentSessionId
      const toolId = this.currentToolCall?.id || this.currentToolCall?.tool_call_id
      if (!runId || !toolId) return
      this.currentToolCall = { ...this.currentToolCall, status: 'cancelled' }
      try {
        await cancelAgentToolApi(runId, toolId)
      } catch {
        // Tool-level cancellation is optional until backend exposes the endpoint.
      }
      this.saveSession()
    },

    /**
     * 重新生成：移除最后一对 user+assistant 消息
     * 返回被移除的 user 消息，供调用方重新发送
     */
    removeLastExchange() {
      // 找到最后一个 assistant
      const lastIdx = this.messages.length - 1
      if (lastIdx < 1) return null
      if (this.messages[lastIdx]?.role !== 'assistant') return null

      const assistantMsg = this.messages.pop()
      const userMsg = this.messages.pop()

      // 清理 image URLs
      (userMsg?.imagePreviewUrls || []).forEach(url => URL.revokeObjectURL(url))
      if (assistantMsg?.detectionPreviewUrl) {
        URL.revokeObjectURL(assistantMsg.detectionPreviewUrl)
      }

      this.currentToolCall = null
      return userMsg
    },

    newChat() {
      this.stopStreaming()
      this.messages.forEach((message) => {
        (message.imagePreviewUrls || []).forEach(url => URL.revokeObjectURL(url))
        if (message.videoUrl) URL.revokeObjectURL(message.videoUrl)
        if (message.detectionPreviewUrl) URL.revokeObjectURL(message.detectionPreviewUrl)
      })
      this.currentSessionId = crypto.randomUUID()
      this.persistCurrentSessionId()
      this.messages = []
      this.currentToolCall = null
      this.errorMessage = ''
      this.connectionStatus = 'idle'
      this.reconnectCount = 0
      this.clearImages()
    },

    saveSession() {
      if (!this.hasMessages) return
      const existing = this.sessions.find(s => s.id === this.currentSessionId)
      const generatedTitle = this.messages.find(m => m.role === 'user')?.content?.slice(0, 30) || '新对话'
      const title = existing?.title || generatedTitle
      const messages = this.messages.map(serializeMessage)
      if (existing) {
        existing.messages = messages
        existing.title = title
        existing.updatedAt = new Date().toISOString()
      } else {
        this.sessions.unshift({
          id: this.currentSessionId,
          title,
          messages,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        })
      }
      this.sessions = this.sessions.slice(0, 20)
      if (this.userScope != null) {
        localStorage.setItem(storageKey(SESSIONS_KEY, this.userScope), JSON.stringify(this.sessions))
      }
    },

    async loadSession(id) {
      const session = this.sessions.find(s => s.id === id)
      if (!session) return
      this.stopStreaming()
      try {
        const remote = await getAgentSession(id)
        this.currentSessionId = session.id
        this.persistCurrentSessionId()
        session.title = remote.title
        session.messages = remote.messages || []
        this.messages = await Promise.all(session.messages.map(async (message) => {
          const attachments = await Promise.all((message.attachments || []).map(async (attachment, index) => {
            if (attachment.previewUrl || !attachment.path) return attachment
            try {
              const blob = await getAgentMessageAttachment(session.id, message.id, index)
              return { ...attachment, previewUrl: URL.createObjectURL(blob) }
            } catch {
              return attachment
            }
          }))
          const restored = restoreMessageCards({
            id: String(message.id),
            role: message.role,
            content: message.content || '',
            attachments,
            imagePreviewUrls: (await Promise.all(
              (message.image_urls || (message.image_url ? [message.image_url] : [])).map(async (_, index) => {
                try {
                  const blob = await getAgentMessageImage(session.id, message.id, index)
                  return URL.createObjectURL(blob)
                } catch {
                  return ''
                }
              }),
            )).filter(Boolean),
            toolCalls: message.tool_calls || [],
            cards: message.cards || message.result_cards || [],
            card_type: message.card_type,
            payload: message.payload,
            task_id: message.task_id,
            model_id: message.model_id,
            file_id: message.file_id,
            knowledge_document_id: message.knowledge_document_id,
            display_order: message.display_order,
            snapshot: message.snapshot,
            createdAt: message.created_at,
          })
          ;(restored.toolCalls || []).forEach(ensureAgentLabel)
          await this.hydrateDetectionImages(restored)
          return restored
        }))
        this.currentToolCall = null
        this.errorMessage = ''
        this.lastRestoreError = ''
        this.clearImages()
        this.saveSession()
      } catch (error) {
        this.lastRestoreError = error?.response?.data?.detail || error?.message || '会话恢复失败'
        throw error
      }
    },

    async renameSession(id, title) {
      const nextTitle = String(title || '').trim()
      if (!nextTitle) throw new Error('会话名称不能为空')
      const session = this.sessions.find(s => s.id === id)
      const previous = session?.title
      if (session) session.title = nextTitle
      try {
        await renameAgentSession(id, nextTitle)
      } catch (error) {
        if (session) session.title = previous
        throw error
      } finally {
        this.saveSessionsMeta()
      }
    },

    async archiveSession(id, archived = true) {
      const session = this.sessions.find(s => s.id === id)
      const previous = session?.archived
      if (session) session.archived = archived
      try {
        await archiveAgentSession(id, archived)
      } catch (error) {
        if (session) session.archived = previous
        throw error
      }
      if (archived && this.currentSessionId === id) this.newChat()
      this.sessions = this.sessions.filter(s => s.id !== id || this.showArchived)
      this.saveSessionsMeta()
    },

    saveSessionsMeta() {
      if (this.userScope != null) {
        localStorage.setItem(storageKey(SESSIONS_KEY, this.userScope), JSON.stringify(this.sessions))
      }
    },

    async hydrateDetectionImages(message) {
      const result = message?.detectionResult
      if (!result) return
      if (Array.isArray(result.items)) {
        await Promise.all(result.items.map(async (item) => {
          item.annotatedImageUrl = await hydrateArtifactUrl(item.annotatedImageUrl)
          item.originalImageUrl = await hydrateArtifactUrl(item.originalImageUrl)
        }))
      } else {
        result.annotatedImageUrl = await hydrateArtifactUrl(result.annotatedImageUrl)
        result.originalImageUrl = await hydrateArtifactUrl(result.originalImageUrl)
      }
    },

    async deleteSession(id) {
      const result = await deleteAgentSession(id)
      this.sessions = this.sessions.filter(s => s.id !== id)
      this.saveSessionsMeta()
      if (this.currentSessionId === id) {
        this.newChat()
      }
      return result
    },
  },
})
