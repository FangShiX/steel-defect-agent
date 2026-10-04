const DETECTION_TOOL_NAMES = new Set([
  'detect_single',
  'detect_batch',
  'detect_zip',
  'detect_video',
  'detection_tool',
  'detect_single_image',
  'defect_detection',
])

const TOOL_CARD_TYPE = {
  get_detection_statistics: 'statistics',
  query_detection_history: 'history',
  search_knowledge: 'knowledge_citations',
  retrieve_knowledge: 'knowledge_citations',
  detect_video: 'video_result',
}

export function parsePayload(payload) {
  if (typeof payload === 'string') {
    try { return JSON.parse(payload) } catch { return payload }
  }
  return payload
}

export function normalizeAgentEvent(event = {}) {
  const raw = parsePayload(event)
  const data = raw?.data && typeof raw.data === 'object' ? { ...raw, ...raw.data } : raw
  const type = data.type || data.event || data.event_type || data.name
  const normalizedType = {
    delta: 'text_delta',
    token: 'text_delta',
    message_delta: 'text_delta',
    tool_call_start: 'tool_start',
    tool_call_delta: 'tool_delta',
    tool_call_result: 'tool_result',
    done: 'message_end',
    finish: 'message_end',
    completed: 'message_end',
    exception: 'error',
    provider_error: 'error',
    cancelled: 'cancelled',
  }[type] || type

  return {
    ...data,
    type: normalizedType,
    content: data.content ?? data.delta ?? data.text ?? '',
    tool_name: data.tool_name || data.tool || data.name,
    tool_call_id: data.tool_call_id || data.toolCallId || data.id,
    result: parsePayload(data.result ?? data.output ?? data.payload),
    error: data.error || data.detail,
  }
}

export function normalizeAgentError(error, fallback = 'Agent request failed') {
  const detail = error?.response?.data?.detail || error?.response?.data || error
  const message = typeof detail === 'string'
    ? detail
    : detail?.message || detail?.detail || error?.message || fallback
  const code = detail?.error_code || detail?.code || error?.code || ''
  const requestId = detail?.request_id || detail?.requestId || error?.requestId || ''
  const retryable = ['NETWORK_ERROR', 'TIMEOUT', 'HTTP_502', 'HTTP_503', 'HTTP_504'].includes(code)
  return { message, code, requestId, retryable }
}

export function normalizeDetectionObjects(items = []) {
  return (items || []).map((item, index) => ({
    id: String(item.id ?? index),
    className: item.class_name || item.className || item.label || 'unknown',
    classNameCn: item.class_name_cn || item.classNameCn || item.class_name || item.label || 'unknown',
    confidence: Number(item.confidence ?? item.score ?? 0),
    bbox: Array.isArray(item.bbox) ? item.bbox.map(Number) : [0, 0, 0, 0],
    bboxPercent: item.bboxPercent || null,
  }))
}

export function normalizeDetectionResult(rawResult = {}, fallback = {}) {
  const payload = parsePayload(rawResult)
  const result = payload?.result || payload
  if (!result || result.error) return null

  if (Array.isArray(result.results) || Array.isArray(result.items)) {
    const rows = result.results || result.items || []
    return {
      taskId: result.task_id || result.taskId || fallback.taskId || '',
      modelId: result.model_id || result.modelId || fallback.modelId || '',
      fileId: result.file_id || result.fileId || fallback.fileId || '',
      totalImages: result.total_images ?? result.totalImages ?? rows.length,
      totalObjects: result.total_objects ?? result.totalObjects ?? rows.reduce((sum, item) => sum + Number(item.total_objects ?? item.totalObjects ?? item.detections?.length ?? item.objects?.length ?? 0), 0),
      items: rows.map((item) => ({
        fileName: item.filename || item.file_name || item.fileName || '',
        originalImageUrl: item.image_url || item.original_image_url || item.originalImageUrl || '',
        annotatedImageUrl: item.annotated_image_url || item.annotatedImageUrl || '',
        totalObjects: item.total_objects ?? item.totalObjects ?? item.detections?.length ?? item.objects?.length ?? 0,
        inferenceTimeMs: Number(item.inference_time ?? item.inference_time_ms ?? item.inferenceTimeMs ?? 0),
        objects: normalizeDetectionObjects(item.detections || item.objects || []),
        error: item.error || null,
      })),
    }
  }

  const detections = result.detections || result.objects || []
  return {
    taskId: result.task_id || result.taskId || fallback.taskId || '',
    modelId: result.model_id || result.modelId || fallback.modelId || '',
    fileId: result.file_id || result.fileId || fallback.fileId || '',
    fileName: result.filename || result.file_name || result.fileName || '',
    originalImageUrl: result.image_url || result.original_image_url || result.originalImageUrl || '',
    annotatedImageUrl: result.annotated_image_url || result.annotatedImageUrl || '',
    totalObjects: result.total_objects ?? result.totalObjects ?? detections.length,
    totalImages: result.total_images ?? result.totalImages ?? 1,
    inferenceTimeMs: Number(result.inference_time ?? result.inference_time_ms ?? result.inferenceTimeMs ?? 0),
    objects: normalizeDetectionObjects(detections),
  }
}

export function inferCardType(toolName = '', result = {}) {
  if (TOOL_CARD_TYPE[toolName]) return TOOL_CARD_TYPE[toolName]
  if (DETECTION_TOOL_NAMES.has(toolName) || result?.detections || result?.results || result?.items) return 'detection_result'
  if (result?.citations || result?.references || result?.knowledge_document_id) return 'knowledge_citations'
  if (result?.total_tasks || result?.total_images || result?.total_objects) return 'statistics'
  return 'tool_result'
}

export function buildAgentCard({ toolName = '', result, status = 'success', meta = {}, displayOrder = 1 } = {}) {
  const payload = parsePayload(result)
  const normalized = payload?.result || payload || {}
  const type = meta.card_type || meta.type || inferCardType(toolName, normalized)
  return {
    id: meta.id || `${toolName || type}-${Date.now()}-${displayOrder}`,
    type,
    card_type: type,
    title: meta.title || '',
    tool_name: toolName,
    status,
    result: normalized,
    payload: normalized,
    references: normalized.references || normalized.citations || meta.references || {},
    task_id: meta.task_id || normalized.task_id || normalized.taskId || normalized.id || '',
    model_id: meta.model_id || normalized.model_id || normalized.modelId || '',
    file_id: meta.file_id || normalized.file_id || normalized.fileId || '',
    knowledge_document_id: meta.knowledge_document_id || normalized.knowledge_document_id || normalized.knowledgeDocumentId || '',
    display_order: meta.display_order ?? normalized.display_order ?? displayOrder,
    snapshot_id: meta.snapshot_id || normalized.snapshot_id || normalized.snapshotId || '',
    snapshot: meta.snapshot || normalized.snapshot || normalized,
  }
}

export function restoreMessageCards(message = {}) {
  const restored = { ...message }
  const explicitCards = restored.cards || restored.result_cards || []
  restored.toolCalls = restored.toolCalls || restored.tool_calls || []
  restored.toolResultCards = [
    ...(restored.toolResultCards || []),
    ...(restored.card_type && restored.payload ? [buildAgentCard({
      toolName: restored.tool_name || restored.card_type,
      result: restored.payload,
      status: restored.status || 'success',
      meta: restored,
      displayOrder: restored.display_order || 1,
    })] : []),
    ...explicitCards.map((card, index) => buildAgentCard({
      toolName: card.tool_name || card.name || card.type,
      result: card.payload || card.result || card.snapshot,
      status: card.status || 'success',
      meta: card,
      displayOrder: card.display_order ?? index + 1,
    })),
  ]

  restored.toolCalls.forEach((tool, index) => {
    const payload = parsePayload(tool.payload ?? tool.result)
    const result = payload?.result || payload
    if (!result || tool.status === 'error') return
    const type = tool.card_type || inferCardType(tool.name || tool.tool_name, result)
    const card = buildAgentCard({
      toolName: tool.name || tool.tool_name,
      result,
      status: tool.status || 'success',
      meta: { ...tool, type },
      displayOrder: tool.display_order ?? index + 1,
    })
    if (type === 'detection_result' && !restored.detectionResult) {
      restored.detectionResult = normalizeDetectionResult(result, card)
    } else if (!restored.toolResultCards.some((item) => item.id === card.id)) {
      restored.toolResultCards.push(card)
    }
  })

  if (restored.videoResult && !restored.toolResultCards.some((card) => card.type === 'video_result')) {
    restored.toolResultCards.push(buildAgentCard({
      toolName: 'detect_video',
      result: restored.videoResult,
      meta: { type: 'video_result' },
      displayOrder: restored.toolResultCards.length + 1,
    }))
  }

  restored.toolResultCards = restored.toolResultCards
    .filter((card) => card.type !== 'detection_result')
    .sort((a, b) => Number(a.display_order || 0) - Number(b.display_order || 0))
  return restored
}
