import request from '@/utils/request'

// Canonical LLM model endpoint used by the LLM store.
export function getLlmModels() {
  return request.get('/agent/models')
}
