import request from "@/utils/request";

export const MAX_BATCH_IMAGES = 20;
export const MAX_VIDEO_FRAMES = 1000;
export const MAX_ZIP_SIZE_BYTES = 50 * 1024 * 1024;

function unwrap(payload) {
  return payload?.data ?? payload;
}

function idempotencyKey(scope) {
  const value = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${scope}:${value}`;
}

function normalizeObject(item, index, imageWidth, imageHeight) {
  const bbox = item.bbox ?? [item.x1, item.y1, item.x2, item.y2];
  const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = bbox;
  return {
    id: String(item.id ?? index),
    classId: item.class_id ?? item.classId ?? 0,
    className: item.class_name ?? item.className ?? "unknown",
    classNameCn:
      item.class_name_cn ?? item.classNameCn ?? item.class_name ?? "未知缺陷",
    confidence: Number(item.confidence ?? 0),
    bbox: [x1, y1, x2, y2].map(Number),
    bboxPercent: imageWidth && imageHeight
      ? [
          (x1 / imageWidth) * 100,
          (y1 / imageHeight) * 100,
          ((x2 - x1) / imageWidth) * 100,
          ((y2 - y1) / imageHeight) * 100,
        ]
      : null,
    areaRatio: item.area_ratio ?? item.areaRatio ?? null,
  };
}

export function normalizeDetectionResponse(payload) {
  const data = unwrap(payload) ?? {};
  const task = data.task ?? data;
  const imageWidth = data.image_width ?? data.imageWidth;
  const imageHeight = data.image_height ?? data.imageHeight;
  const rawObjects = data.objects ?? data.results ?? data.defect_results ?? [];
  const objects = rawObjects.map((item, index) =>
    normalizeObject(item, index, imageWidth, imageHeight),
  );
  return {
    taskId: String(task.id ?? data.record_id ?? data.task_id ?? data.taskId ?? ""),
    publicTaskId: String(
      task.public_task_id ?? data.public_task_id ?? data.publicTaskId ??
      task.id ?? data.record_id ?? data.task_id ?? data.taskId ?? "",
    ),
    status: task.status ?? data.status ?? "completed",
    fileName: data.filename ?? data.fileName ?? "",
    originalImageUrl: data.image_url ?? data.originalImageUrl ?? "",
    annotatedImageUrl:
      data.annotated_image_url ?? data.result_image_url ?? data.annotatedImageUrl ?? "",
    totalImages: task.total_images ?? data.totalImages ?? 1,
    totalObjects:
      task.total_objects ?? data.totalObjects ?? data.summary?.total ?? objects.length,
    inferenceTimeMs:
      task.total_inference_time ?? data.inference_time_ms ?? data.inferenceTimeMs ??
      (data.detection_time != null ? data.detection_time * 1000 : 0),
    imageWidth,
    imageHeight,
    objects,
  };
}

export async function detectSingleApi(file, options) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("model_id", options.modelId);
  formData.append("conf_threshold", String(options.confThreshold));
  formData.append("iou_threshold", String(options.iouThreshold));
  const response = await request.post("/detection/single", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
      "Idempotency-Key": idempotencyKey("single"),
    },
    timeout: 120000,
  });
  return normalizeDetectionResponse(response);
}

export async function detectBatchApi(files, options) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  formData.append("model_id", options.modelId);
  formData.append("conf_threshold", String(options.confThreshold));
  formData.append("iou_threshold", String(options.iouThreshold));
  const data = unwrap(
    await request.post("/detection/batch", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
        "Idempotency-Key": idempotencyKey("batch"),
      },
      timeout: 300000,
    }),
  );
  return {
    taskId: String(data.task_id ?? data.taskId ?? ""),
    publicTaskId: String(data.public_task_id ?? data.publicTaskId ?? data.task_id ?? ""),
    status: data.status ?? "completed",
    successCount: data.success_count ?? data.successCount ?? 0,
    failedCount: data.failed_count ?? data.failedCount ?? 0,
    items: (data.items ?? []).map((item) => ({
      ...normalizeDetectionResponse(item),
      status: item.status,
      fileName: item.file_name ?? item.fileName ?? "",
      error: item.error ?? null,
    })),
  };
}

export async function detectZipApi(file, options) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("model_id", options.modelId);
  formData.append("conf_threshold", String(options.confThreshold));
  formData.append("iou_threshold", String(options.iouThreshold));
  const data = unwrap(await request.post("/detection/zip", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
      "Idempotency-Key": idempotencyKey("zip"),
    },
    timeout: 300000,
  }));
  return {
    taskId: String(data.task_id ?? ""),
    publicTaskId: String(data.public_task_id ?? data.task_id ?? ""),
    status: data.status ?? "completed",
    source: data.source ?? "zip",
    zipFilename: data.zip_filename ?? file.name,
    totalImagesInZip: data.total_images_in_zip ?? data.items?.length ?? 0,
    successCount: data.success_count ?? 0,
    failedCount: data.failed_count ?? 0,
    items: (data.items ?? []).map((item) => ({
      ...normalizeDetectionResponse(item),
      status: item.status,
      fileName: item.file_name ?? "",
      error: item.error ?? null,
    })),
  };
}

export async function detectVideoApi(file, options) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("model_id", options.modelId);
  formData.append("conf_threshold", String(options.confThreshold ?? 0.25));
  formData.append("iou_threshold", String(options.iouThreshold ?? 0.45));
  formData.append("frame_sample_rate", String(options.frameSampleRate ?? 5));
  formData.append("max_frames", String(options.maxFrames ?? MAX_VIDEO_FRAMES));
  return unwrap(await request.post("/detection/video", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
      "Idempotency-Key": idempotencyKey("video"),
    },
    timeout: 120000,
  }));
}

export async function getVideoStatusApi(taskId) {
  return unwrap(await request.get(`/detection/video/status/${taskId}`));
}

export function getDetectionModelStatus() {
  return request.get("/detection/models/status");
}
