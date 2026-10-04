import request from '@/utils/request'

// 会话 CRUD 的唯一前端入口；Agent API 仅保留流式响应和富消息/附件读取。
export function listChatSessions(params = {}) {
  return request.get('/chat/sessions', { params })
}

export function renameChatSession(sessionId, title) {
  return request.patch(`/chat/sessions/${encodeURIComponent(sessionId)}/title`, null, { params: { title } })
}

export function archiveChatSession(sessionId) {
  return request.post(`/chat/sessions/${encodeURIComponent(sessionId)}/archive`)
}

export function deleteChatSession(sessionId) {
  return request.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`)
}

// Canonical history read. The Agent endpoint remains responsible for the
// stream and protected attachment/artifact bytes, not session CRUD.
export async function getChatSession(sessionId) {
  const payload = await request.get(`/chat/sessions/${encodeURIComponent(sessionId)}/history`)
  return {
    ...(payload?.session || {}),
    messages: payload?.messages || [],
  }
}

export function getChatMessageImage(sessionId, messageId, index = 0) {
  return request.get(`/agent/sessions/${encodeURIComponent(sessionId)}/messages/${messageId}/image`, {
    params: { index },
    responseType: 'blob',
  })
}

export function getChatArtifact(filename) {
  return request.get(`/agent/artifacts/${encodeURIComponent(filename)}`, {
    responseType: 'blob',
  })
}
