import request from "@/utils/request";

function unwrap(payload) {
  return payload?.data ?? payload;
}

export function normalizeDashboardResponse(payload) {
  const data = unwrap(payload) ?? {};
  return {
    totals: {
      totalTasks: data.totals?.totalTasks ?? data.total_tasks ?? 0,
      totalImages: data.totals?.totalImages ?? data.total_images ?? 0,
      totalObjects: data.totals?.totalObjects ?? data.total_objects ?? 0,
      avgInferenceTimeMs:
        data.totals?.avgInferenceTimeMs ?? data.avg_inference_time ?? 0,
      trainingTasks: data.totals?.trainingTasks ?? data.training_total_tasks ?? 0,
    },
    classDistribution:
      data.classDistribution ??
      Object.entries(data.class_distribution ?? {}).map(([name, value]) => ({
        name,
        value,
      })),
    dailyTrend: (data.dailyTrend ?? data.daily_trend ?? []).map((item) => ({
      date: item.date,
      tasks: Number(item.tasks ?? item.count ?? item.images ?? 0),
    })),
    trainingDailyTrend: (data.trainingDailyTrend ?? data.training_daily_trend ?? []).map((item) => ({ date: item.date, tasks: Number(item.tasks ?? item.count ?? 0) })),
    sceneDistribution:
      data.sceneDistribution ??
      Object.entries(data.scene_distribution ?? {}).map(([name, value]) => ({
        name,
        value,
      })),
    confidenceDistribution:
      data.confidenceDistribution ?? data.confidence_distribution ?? [],
    dailyInferenceTime: (data.dailyInferenceTime ?? data.daily_inference_time ?? []).map((item) => ({
      date: item.date,
      min: Number(item.min ?? 0),
      max: Number(item.max ?? 0),
      avg: Number(item.avg ?? 0),
    })),
    modelMetrics: data.modelMetrics ?? data.model_metrics ?? [],
    updatedAt: data.updatedAt ?? data.updated_at ?? "",
  };
}

export async function getDashboardApi(params = {}) {
  return normalizeDashboardResponse(
    await request.get("/history/statistics/summary", {
      params: Object.fromEntries(Object.entries({
        days: params.days ?? 30,
        scene_id: params.sceneId,
        task_type: params.taskType,
        status: params.status,
        media_type: params.mediaType,
        keyword: params.keyword,
        owner_user_id: params.userId,
        start_date: params.startDate,
        end_date: params.endDate,
      }).filter(([, value]) => value !== '' && value != null)),
    }),
  );
}

export function exportStatisticsApi(params = {}) {
  return request.get('/history/statistics/export', {
    responseType: 'blob',
    params: {
      days: params.days,
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
