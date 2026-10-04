import request from "@/utils/request";

function unwrap(payload) {
  return payload?.data ?? payload;
}

export async function getScenesApi() {
  const response = unwrap(await request.get("/scenes"));
  return (response?.items ?? response ?? []).map((scene) => ({
    id: String(scene.id),
    name: scene.name,
    displayName: scene.display_name ?? scene.displayName ?? scene.name,
    classNames: scene.class_names ?? scene.classNames ?? [],
  }));
}

export async function getModelsApi(sceneId) {
  const models = unwrap(await request.get(`/scenes/${sceneId}/models`));
  return (models ?? []).map((model) => ({
    id: String(model.id),
    version: model.version,
    modelName: model.model_name ?? model.modelName,
    modelType: model.model_type ?? model.modelType,
    map50: model.map50,
    precision: model.precision,
    recall: model.recall,
    isDefault: model.is_default ?? model.isDefault ?? false,
    status: model.status ?? "active",
    modelPath: model.model_path ?? model.modelPath ?? '',
    ownerId: model.owner_id ?? model.ownerId ?? null,
    isBuiltin: model.is_builtin ?? model.isBuiltin ?? false,
    fileSize: model.file_size ?? model.fileSize ?? null,
    cleanupPending: model.cleanup_pending ?? model.cleanupPending ?? false,
    cleanupError: model.cleanup_error ?? model.cleanupError ?? null,
    cleanupRetryCount: model.cleanup_retry_count ?? model.cleanupRetryCount ?? 0,
    createdAt: model.created_at ?? model.createdAt ?? null,
  }));
}

export function setDefaultModelApi(sceneId, modelVersionId) {
  return request.post(`/scenes/${sceneId}/default-model`, null, {
    params: { model_version_id: Number(modelVersionId) },
  })
}

export function downloadModelVersionApi(sceneId, modelVersionId) {
  return request.get(`/scenes/${sceneId}/models/${modelVersionId}/download`, { responseType: 'blob', timeout: 120000 })
}

export function deleteModelVersionApi(sceneId, modelVersionId) {
  return request.delete(`/scenes/${sceneId}/models/${modelVersionId}`)
}

export function archiveModelVersionApi(sceneId, modelVersionId) {
  return request.post(`/scenes/${sceneId}/models/${modelVersionId}/archive`)
}

export function retryModelCleanupApi(sceneId, modelVersionId) {
  return request.post(`/scenes/${sceneId}/models/${modelVersionId}/retry-cleanup`)
}

export function uploadModelVersionApi(sceneId, payload) {
  const formData = new FormData()
  formData.append('file', payload.file)
  formData.append('version', payload.version)
  formData.append('model_name', payload.modelName)
  formData.append('model_type', payload.modelType || 'yolo11n')
  if (payload.description) formData.append('description', payload.description)
  return request.post(`/scenes/${sceneId}/models/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export function updateModelVersionApi(sceneId, modelVersionId, payload) {
  const formData = new FormData()
  if (payload.version != null) formData.append('version', payload.version)
  if (payload.modelName != null) formData.append('model_name', payload.modelName)
  if (payload.description != null) formData.append('description', payload.description)
  return request.patch(`/scenes/${sceneId}/models/${modelVersionId}`, formData)
}
