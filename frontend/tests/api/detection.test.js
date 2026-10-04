import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/utils/request", () => ({ default: request }));

import {
  detectVideoApi,
  detectZipApi,
  getVideoStatusApi,
  normalizeDetectionResponse,
} from "@/api/detection";

describe("detection api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes the local YOLO snake_case response", () => {
    const result = normalizeDetectionResponse({
      task_id: 42,
      status: "completed",
      filename: "steel.webp",
      image_width: 640,
      image_height: 480,
      total_objects: 1,
      inference_time_ms: 37.5,
      objects: [
        {
          class_id: 3,
          class_name: "pitted",
          class_name_cn: "pitted defect",
          confidence: 0.88,
          bbox: [16, 24, 116, 124],
        },
      ],
    });

    expect(result.taskId).toBe("42");
    expect(result.inferenceTimeMs).toBe(37.5);
    expect(result.fileName).toBe("steel.webp");
    expect(result.objects[0].className).toBe("pitted");
  });

  it("按后端契约提交 ZIP 检测并规范化批量结果", async () => {
    request.post.mockResolvedValue({
      task_id: 11,
      status: "completed",
      success_count: 1,
      failed_count: 0,
      items: [{ file_name: "steel.jpg", status: "completed", total_objects: 2 }],
    });
    const file = new File(["zip-content"], "images.zip", {
      type: "application/zip",
    });

    const result = await detectZipApi(file, {
      modelId: 3,
      confThreshold: 0.3,
      iouThreshold: 0.5,
    });

    const [url, formData, config] = request.post.mock.calls[0];
    expect(url).toBe("/detection/zip");
    expect(formData.get("file").name).toBe("images.zip");
    expect(formData.get("model_id")).toBe("3");
    expect(formData.get("conf_threshold")).toBe("0.3");
    expect(formData.get("iou_threshold")).toBe("0.5");
    expect(config.timeout).toBe(300000);
    expect(result).toMatchObject({
      taskId: "11",
      successCount: 1,
      failedCount: 0,
    });
  });

  it("创建视频任务并使用任务 ID 查询进度", async () => {
    request.post.mockResolvedValue({ task_id: 21, status: "processing" });
    request.get.mockResolvedValue({
      task_id: 21,
      status: "processing",
      progress: 35,
    });
    const file = new File(["video-content"], "demo.mp4", {
      type: "video/mp4",
    });

    await detectVideoApi(file, {
      modelId: 4,
      confThreshold: 0.25,
      iouThreshold: 0.45,
      frameSampleRate: 6,
      maxFrames: 40,
    });
    const status = await getVideoStatusApi(21);

    const [url, formData, config] = request.post.mock.calls[0];
    expect(url).toBe("/detection/video");
    expect(formData.get("frame_sample_rate")).toBe("6");
    expect(formData.get("max_frames")).toBe("40");
    expect(config.timeout).toBe(120000);
    expect(request.get).toHaveBeenCalledWith("/detection/video/status/21");
    expect(status.progress).toBe(35);
  });
});
