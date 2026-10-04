import { defineStore } from 'pinia'
import { getTrainingTasks } from '@/api/training'
import { getHistoryApi } from '@/api/history'
import { getVideoStatusApi } from '@/api/detection'

const SELECTED_TRAINING_TASK_KEY = 'ssdd_selected_training_task_id'

function readSelectedTrainingTaskId() {
  const value = sessionStorage.getItem(SELECTED_TRAINING_TASK_KEY)
  return value ? Number(value) : null
}

export const useTaskStore = defineStore('tasks', {
  state: () => ({
    trainingTasks: [],
    loadingTrainingTasks: false,
    selectedTrainingTaskId: readSelectedTrainingTaskId(),
    detectionTasks: [],
    loadingDetectionTasks: false,
  }),

  getters: {
    selectedTrainingTask: (state) => state.trainingTasks.find(
      (task) => task.id === state.selectedTrainingTaskId,
    ) || null,
  },

  actions: {
    async fetchTrainingTasks() {
      this.loadingTrainingTasks = true
      try {
        const response = await getTrainingTasks()
        this.trainingTasks = response.items || []
        if (this.selectedTrainingTaskId && !this.selectedTrainingTask) {
          this.clearSelectedTrainingTask()
        }
        return this.trainingTasks
      } finally {
        this.loadingTrainingTasks = false
      }
    },

    async fetchDetectionTasks() {
      this.loadingDetectionTasks = true
      try {
        const response = await getHistoryApi({ page: 1, pageSize: 100 })
        const tasks = response.items || []
        const activeVideos = tasks.filter(
          (task) => task.taskType === 'video' && ['pending', 'processing'].includes(task.status),
        )
        const progressResults = await Promise.allSettled(activeVideos.map(async (task) => ({
          id: task.id,
          data: await getVideoStatusApi(task.id),
        })))
        const progressMap = new Map(progressResults
          .filter((result) => result.status === 'fulfilled')
          .map((result) => [result.value.id, result.value.data]))
        this.detectionTasks = tasks.map((task) => {
          const current = progressMap.get(task.id)
          return current ? {
            ...task,
            status: current.status ?? task.status,
            progress: current.progress ?? 0,
            errorMessage: current.status === 'failed' ? (current.message || task.errorMessage) : task.errorMessage,
          } : task
        })
        return this.detectionTasks
      } finally {
        this.loadingDetectionTasks = false
      }
    },

    upsertTrainingTask(task) {
      const index = this.trainingTasks.findIndex((item) => item.id === task.id)
      if (index === -1) this.trainingTasks.push(task)
      else this.trainingTasks[index] = { ...this.trainingTasks[index], ...task }
    },

    selectTrainingTask(taskId) {
      this.selectedTrainingTaskId = taskId ?? null
      if (this.selectedTrainingTaskId) {
        sessionStorage.setItem(SELECTED_TRAINING_TASK_KEY, String(this.selectedTrainingTaskId))
      } else {
        sessionStorage.removeItem(SELECTED_TRAINING_TASK_KEY)
      }
    },

    clearSelectedTrainingTask() {
      this.selectTrainingTask(null)
    },
  },
})
