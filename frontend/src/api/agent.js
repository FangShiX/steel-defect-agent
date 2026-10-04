import { streamChat } from '@/utils/stream'
import request from '@/utils/request'
import { getHistoryApi, getHistoryDetailApi } from '@/api/history'

export function streamAgentChat(payload, callbacks) {
  return streamChat('/api/agent/chat/stream', payload, callbacks, {
    maxRetries: 1,
    retryDelay: 1000,
  })
}

export function getAgentModelsApi() {
  return request.get('/agent/models')
}

export function getCachedAgentModelsApi() {
  return request.get('/agent/models/cached')
}

export function uploadAgentImageApi(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/agent/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getAgentDetectionHistoryApi(params = {}) {
  return getHistoryApi(params)
}

export function getAgentDetectionHistoryDetailApi(taskId) {
  return getHistoryDetailApi(taskId)
}

export function listAgentSessions(params = {}) {
  return request.get('/agent/sessions', { params })
}

export function getAgentSession(sessionId) {
  return request.get(`/agent/sessions/${encodeURIComponent(sessionId)}`)
}

export function getAgentMessageImage(sessionId, messageId, index = 0) {
  return request.get(`/agent/sessions/${encodeURIComponent(sessionId)}/messages/${messageId}/image`, {
    params: { index },
    responseType: 'blob',
  })
}

export function getAgentMessageAttachment(sessionId, messageId, index = 0) {
  return request.get(`/agent/sessions/${encodeURIComponent(sessionId)}/messages/${messageId}/attachment`, {
    params: { index },
    responseType: 'blob',
  })
}

export function getAgentArtifact(filename) {
  return request.get(`/agent/artifacts/${encodeURIComponent(filename)}`, {
    responseType: 'blob',
  })
}

export function deleteAgentSession(sessionId) {
  return request.delete(`/agent/sessions/${encodeURIComponent(sessionId)}`)
}

export function updateAgentSession(sessionId, payload) {
  // TODO(backend): PATCH /api/agent/sessions/{id} should persist title/archived metadata.
  return request.patch(`/agent/sessions/${encodeURIComponent(sessionId)}`, payload)
}

export function renameAgentSession(sessionId, title) {
  return updateAgentSession(sessionId, { title })
}

export function archiveAgentSession(sessionId, archived = true) {
  return updateAgentSession(sessionId, { archived })
}

export function cancelAgentRunApi(runId) {
  // TODO(backend): POST /api/agent/runs/{id}/cancel should stop the whole agent request.
  return request.post(`/agent/runs/${encodeURIComponent(runId)}/cancel`)
}

export function cancelAgentToolApi(runId, toolCallId) {
  // TODO(backend): POST /api/agent/runs/{id}/tools/{toolCallId}/cancel should stop one running tool.
  return request.post(`/agent/runs/${encodeURIComponent(runId)}/tools/${encodeURIComponent(toolCallId)}/cancel`)
}
