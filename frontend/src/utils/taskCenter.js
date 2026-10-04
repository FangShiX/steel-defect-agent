const ACTIVE_STATUSES = new Set(["pending", "processing", "running"]);

function numericProgress(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.min(100, Math.max(0, number));
}

export function buildTaskCenterItems({ trainingTasks = [], detectionTasks = [] } = {}) {
  const training = trainingTasks.map((task) => {
    const taskId = task.taskId ?? task.id;
    const taskName = task.taskName ?? task.task_name;
    const sceneName = task.sceneName ?? task.scene_name;
    const datasetName = task.datasetName ?? task.dataset_name ?? task.dataset_path;
    const modelName = task.modelName ?? task.model_name;
    const currentEpoch = task.currentEpoch ?? task.current_epoch ?? 0;
    const totalEpochs = task.totalEpochs ?? task.total_epochs ?? task.epochs ?? 0;
    const epochProgress = totalEpochs > 0
      ? (Number(currentEpoch) / Number(totalEpochs)) * 100
      : 0;
    const progress = task.status === "completed"
      ? 100
      : numericProgress(task.progress || epochProgress);
    return {
      key: `training-${taskId}`,
      id: taskId,
      category: "training",
      taskType: "training",
      title: taskName,
      description: [sceneName, datasetName, modelName].filter(Boolean).join(" · "),
      status: task.status,
      progress,
      errorMessage: task.errorMessage ?? task.error_message,
      createdAt: task.createdAt ?? task.created_at,
      completedAt: task.completedAt ?? task.completed_at,
    };
  });

  const detection = detectionTasks.map((task) => ({
    key: `detection-${task.id}`,
    id: task.id,
    category: "detection",
    taskType: task.taskType,
    title: `${task.taskType || "detection"} #${task.id}`,
    description: task.sceneName,
    status: task.status,
    progress: task.status === "completed" ? 100 : numericProgress(task.progress),
    errorMessage: task.errorMessage,
    createdAt: task.createdAt,
    completedAt: task.completedAt,
  }));

  return [...training, ...detection].sort((left, right) => {
    const leftTime = new Date(left.createdAt || 0).getTime();
    const rightTime = new Date(right.createdAt || 0).getTime();
    return rightTime - leftTime;
  });
}

export function filterTaskCenterItems(items, filters = {}) {
  const keyword = String(filters.keyword ?? "").trim().toLowerCase();
  return items.filter((item) => {
    if (filters.category && item.category !== filters.category) return false;
    if (filters.status && item.status !== filters.status) return false;
    if (!keyword) return true;
    return [item.id, item.title, item.description, item.taskType, item.status]
      .some((value) => String(value ?? "").toLowerCase().includes(keyword));
  });
}

export function hasActiveTasks(items) {
  return items.some((item) => ACTIVE_STATUSES.has(item.status));
}
