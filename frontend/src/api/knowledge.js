import request from '@/utils/request'

// Knowledge-base management APIs consumed by the admin page and Agent RAG.
export function getKnowledgeDocumentsApi() {
  return request.get('/knowledge/documents')
}

export function uploadKnowledgeDocumentApi(title, file, isSystem = false) {
  const formData = new FormData()
  if (title) formData.append('title', title)
  formData.append('is_system', String(isSystem))
  formData.append('file', file)
  return request.post('/knowledge/documents', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export function getKnowledgeDocumentChunksApi(documentId) {
  return request.get(`/knowledge/documents/${documentId}/chunks`)
}

export function downloadKnowledgeDocumentApi(documentId) {
  return request.get(`/knowledge/documents/${documentId}/download`, { responseType: 'blob', timeout: 120000 })
}

export function deleteKnowledgeDocumentApi(documentId) {
  return request.delete(`/knowledge/documents/${documentId}`)
}
