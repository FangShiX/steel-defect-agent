import request from "@/utils/request";

export const HISTORY_TASK_TYPE_OPTIONS = [
  { value: "single", label: "单图检测" },
  { value: "batch", label: "批量检测" },
  { value: "zip", label: "ZIP 检测" },
  { value: "video", label: "视频检测" },
  { value: "camera", label: "摄像头检测" },
];

export function getHistoryTaskTypeLabel(value) {
  return (
    HISTORY_TASK_TYPE_OPTIONS.find((item) => item.value === value)?.label ||
    value ||
    "—"
  );
}

export function getHistoryMediaType(value) {
  if (value === "video") return "video";
  if (value === "camera") return "frame";
  return "image";
}

function unwrap(payload) {
  return payload?.data ?? payload;
}

function numericId(value) {
  if (value === "" || value == null) return "";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : value;
}

export function normalizeHistoryTask(task = {}) {
  const id = numericId(task.id ?? task.task_id ?? task.taskId);
  const totalImages = Number(task.total_images ?? task.totalImages ?? 0);
  const totalInferenceTimeMs = Number(
    task.total_inference_time ?? task.totalInferenceTimeMs ?? 0,
  );

  return {
    id,
    publicTaskId: String(
      task.public_task_id ?? task.publicTaskId ?? id ?? "",
    ),
    sceneId: numericId(task.scene_id ?? task.sceneId),
    sceneName: task.scene_name ?? task.sceneName ?? "未命名场景",
    modelVersionId: numericId(
      task.model_version_id ?? task.modelVersionId ?? "",
    ),
    taskType: task.task_type ?? task.taskType ?? "single",
    mediaType: getHistoryMediaType(task.task_type ?? task.taskType ?? "single"),
    status: task.status ?? "pending",
    totalImages,
    totalObjects: Number(task.total_objects ?? task.totalObjects ?? 0),
    totalInferenceTimeMs,
    avgInferenceTimeMs: totalImages > 0 ? totalInferenceTimeMs / totalImages : 0,
    confThreshold: Number(task.conf_threshold ?? task.confThreshold ?? 0),
    iouThreshold: Number(task.iou_threshold ?? task.iouThreshold ?? 0),
    errorMessage: task.error_message ?? task.errorMessage ?? "",
    createdAt: task.created_at ?? task.createdAt ?? "",
    completedAt: task.completed_at ?? task.completedAt ?? "",
  };
}

export function normalizeHistoryPage(payload) {
  const data = unwrap(payload) ?? {};
  const items = data.items ?? data.records ?? [];
  return {
    items: items.map(normalizeHistoryTask),
    total: Number(data.total ?? items.length),
    page: Number(data.page ?? 1),
    pageSize: Number(data.page_size ?? data.pageSize ?? 20),
    totalPages: Number(data.total_pages ?? data.totalPages ?? 0),
  };
}

export function normalizeHistoryDetail(payload) {
  const data = unwrap(payload) ?? {};
  return {
    task: normalizeHistoryTask(data.task ?? data),
    results: (data.results ?? []).map((result) => ({
      id: numericId(result.id),
      imagePath: result.image_path ?? result.imagePath ?? "",
      annotatedImageUrl:
        result.annotated_image_url ?? result.annotatedImageUrl ?? "",
      className: result.class_name ?? result.className ?? "unknown",
      classNameCn:
        result.class_name_cn ?? result.classNameCn ?? result.class_name ?? "未知缺陷",
      confidence: Number(result.confidence ?? 0),
      bbox: (result.bbox ?? []).map(Number),
      inferenceTimeMs: Number(
        result.inference_time ?? result.inferenceTimeMs ?? 0,
      ),
      imageWidth: result.image_width ?? result.imageWidth ?? null,
      imageHeight: result.image_height ?? result.imageHeight ?? null,
      createdAt: result.created_at ?? result.createdAt ?? "",
    })),
  };
}

export async function getHistoryApi(params = {}) {
  const response = await request.get("/history", {
    params: Object.fromEntries(
      Object.entries({
        scene_id: params.sceneId,
        task_type: params.taskType,
        status: params.status,
        media_type: params.mediaType,
        keyword: params.keyword,
        owner_user_id: params.ownerUserId,
        start_date: params.startDate,
        end_date: params.endDate,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
      }).filter(([, value]) => value !== "" && value != null),
    ),
  });
  return normalizeHistoryPage(response);
}

export async function getHistoryDetailApi(taskId) {
  return normalizeHistoryDetail(await request.get(`/history/${taskId}`));
}

export function deleteHistoryApi(taskId) {
  return request.delete(`/history/${taskId}`);
}

export function exportHistoryApi(params = {}) {
  return request.get('/history/export', {
    responseType: 'blob',
    params: {
      scene_id: params.sceneId || undefined,
      task_type: params.taskType || undefined,
      status: params.status || undefined,
      media_type: params.mediaType || undefined,
      keyword: params.keyword || undefined,
      owner_user_id: params.ownerUserId || undefined,
      start_date: params.startDate || undefined,
      end_date: params.endDate || undefined,
    },
  })
}
