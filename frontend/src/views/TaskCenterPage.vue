<template>
  <div class="task-center-page">
    <ModulePageHeader :title="text.title" :description="text.description">
      <span v-if="lastUpdated" class="last-updated">{{ text.updated }} {{ formatDate(lastUpdated) }}</span>
      <el-button :icon="Refresh" :loading="loading" @click="loadTasks()">{{ text.refresh }}</el-button>
    </ModulePageHeader>

    <PageErrorAlert
      v-if="pageError"
      :message="pageError"
      :retry-text="text.reload"
      @retry="loadTasks()"
    />

    <div class="summary-grid">
      <div class="summary-card"><span>{{ text.allTasks }}</span><strong>{{ tasks.length }}</strong></div>
      <div class="summary-card active"><span>{{ text.activeTasks }}</span><strong>{{ activeCount }}</strong></div>
      <div class="summary-card success"><span>{{ text.completedTasks }}</span><strong>{{ completedCount }}</strong></div>
      <div class="summary-card danger"><span>{{ text.failedTasks }}</span><strong>{{ failedCount }}</strong></div>
    </div>

    <section class="task-panel">
      <div class="task-toolbar">
        <el-input
          v-model.trim="filters.keyword"
          clearable
          :prefix-icon="Search"
          :placeholder="text.searchPlaceholder"
        />
        <el-select v-model="filters.category" clearable :placeholder="text.allCategories">
          <el-option :label="text.training" value="training" />
          <el-option :label="text.detection" value="detection" />
        </el-select>
        <el-select v-model="filters.status" clearable :placeholder="text.allStatuses">
          <el-option v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <span v-if="autoRefreshing" class="auto-refresh"><i />{{ text.autoRefreshing }}</span>
      </div>

      <el-table v-loading="loading" :data="filteredTasks" row-key="key" :empty-text="text.empty">
        <el-table-column :label="text.category" width="105">
          <template #default="{ row }">
            <el-tag :type="row.category === 'training' ? 'primary' : 'info'" effect="plain">
              {{ row.category === 'training' ? text.training : text.detection }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="text.task" min-width="210" show-overflow-tooltip>
          <template #default="{ row }">
            <strong class="task-title">{{ taskTitle(row) }}</strong>
            <span class="task-description">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="text.status" width="112">
          <template #default="{ row }"><StatusTag :status="row.status" :label="statusLabel(row.status)" /></template>
        </el-table-column>
        <el-table-column :label="text.progress" min-width="170">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(row.progress)"
              :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : undefined"
            />
          </template>
        </el-table-column>
        <el-table-column :label="text.createdAt" width="180" sortable prop="createdAt">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column :label="text.failureReason" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.errorMessage || '—' }}</template>
        </el-table-column>
        <el-table-column :label="text.actions" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openTask(row)">{{ text.view }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { Refresh, Search } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { getHistoryTaskTypeLabel } from '@/api/history'
import ModulePageHeader from '@/components/common/ModulePageHeader.vue'
import PageErrorAlert from '@/components/common/PageErrorAlert.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { useSettingsStore } from '@/stores/settings'
import { useTaskStore } from '@/stores/tasks'
import { getApiErrorMessage } from '@/utils/apiError'
import { buildTaskCenterItems, filterTaskCenterItems, hasActiveTasks } from '@/utils/taskCenter'

const router = useRouter()
const settingsStore = useSettingsStore()
const taskStore = useTaskStore()
const { trainingTasks, detectionTasks } = storeToRefs(taskStore)
const loading = ref(false)
const pageError = ref('')
const lastUpdated = ref('')
const filters = reactive({ keyword: '', category: '', status: '' })
let refreshTimer

const text = computed(() => settingsStore.isEnglish ? {
  title: 'Task Center', description: 'Track real training and detection tasks in one place. Active tasks refresh automatically.',
  updated: 'Updated', refresh: 'Refresh', reload: 'Reload', allTasks: 'All tasks', activeTasks: 'Active', completedTasks: 'Completed', failedTasks: 'Failed',
  searchPlaceholder: 'Search ID, task name, scene or model', allCategories: 'All categories', allStatuses: 'All statuses', training: 'Training', detection: 'Detection',
  autoRefreshing: 'Auto refresh is on', category: 'Category', task: 'Task', status: 'Status', progress: 'Progress', createdAt: 'Created at', failureReason: 'Failure reason', actions: 'Actions', view: 'View', empty: 'No tasks match the current filters',
  pending: 'Pending', processing: 'Processing', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', loadFailed: 'Failed to load task center',
} : {
  title: '任务中心', description: '统一查看真实训练任务和检测任务，进行中的任务会自动刷新。',
  updated: '更新时间', refresh: '刷新', reload: '重新加载', allTasks: '全部任务', activeTasks: '进行中', completedTasks: '已完成', failedTasks: '失败',
  searchPlaceholder: '搜索任务 ID、名称、场景或模型', allCategories: '全部任务类别', allStatuses: '全部状态', training: '训练', detection: '检测',
  autoRefreshing: '正在自动刷新', category: '类别', task: '任务', status: '状态', progress: '进度', createdAt: '创建时间', failureReason: '失败原因', actions: '操作', view: '查看', empty: '当前筛选条件下暂无任务',
  pending: '等待中', processing: '处理中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', loadFailed: '任务中心加载失败',
})

const statusOptions = computed(() => ['pending', 'processing', 'running', 'completed', 'failed', 'cancelled'].map((value) => ({ value, label: statusLabel(value) })))
const tasks = computed(() => buildTaskCenterItems({ trainingTasks: trainingTasks.value, detectionTasks: detectionTasks.value }))
const filteredTasks = computed(() => filterTaskCenterItems(tasks.value, filters))
const activeCount = computed(() => tasks.value.filter((item) => ['pending', 'processing', 'running'].includes(item.status)).length)
const completedCount = computed(() => tasks.value.filter((item) => item.status === 'completed').length)
const failedCount = computed(() => tasks.value.filter((item) => item.status === 'failed').length)
const autoRefreshing = computed(() => hasActiveTasks(tasks.value))

function statusLabel(status) {
  return text.value[status] || status || '—'
}

function taskTitle(row) {
  if (row.category === 'training') return row.title || `${text.value.training} #${row.id}`
  const englishTypes = { single: 'Single image', batch: 'Batch', zip: 'ZIP', video: 'Video', camera: 'Camera' }
  const typeLabel = settingsStore.isEnglish ? (englishTypes[row.taskType] || row.taskType) : getHistoryTaskTypeLabel(row.taskType)
  return `${typeLabel} #${row.id}`
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(settingsStore.isEnglish ? 'en-US' : 'zh-CN', { hour12: false })
}

async function loadTasks(options = {}) {
  if (!options.silent) loading.value = true
  pageError.value = ''
  const [trainingResult, detectionResult] = await Promise.allSettled([
    taskStore.fetchTrainingTasks(),
    taskStore.fetchDetectionTasks(),
  ])
  const errors = []
  if (trainingResult.status === 'rejected') errors.push(getApiErrorMessage(trainingResult.reason, text.value.loadFailed))
  if (detectionResult.status === 'rejected') errors.push(getApiErrorMessage(detectionResult.reason, text.value.loadFailed))
  pageError.value = [...new Set(errors)].join('；')
  lastUpdated.value = new Date().toISOString()
  loading.value = false
}

function openTask(row) {
  if (row.category === 'training') {
    taskStore.selectTrainingTask(row.id)
    router.push({ name: 'Training' })
  } else {
    router.push({ name: 'History', query: { task: row.id } })
  }
}

watch([trainingTasks, detectionTasks], () => { lastUpdated.value = new Date().toISOString() }, { deep: true })
onMounted(async () => {
  await loadTasks()
  refreshTimer = window.setInterval(() => {
    if (autoRefreshing.value && !loading.value) loadTasks({ silent: true })
  }, 5000)
})
onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<style lang="scss" scoped>
.task-center-page { max-width: 1200px; min-height: 100%; margin: 0 auto; }
.last-updated { color: $text-secondary; font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.summary-card { padding: 17px 18px; border: 1px solid #e7ebf1; border-radius: 14px; background: var(--app-surface); box-shadow: 0 8px 24px rgba(28, 39, 60, .04); }
.summary-card span { display: block; color: $text-secondary; font-size: 12px; }
.summary-card strong { display: block; margin-top: 7px; color: var(--app-text); font-size: 28px; }
.summary-card.active strong { color: #2563eb; }
.summary-card.success strong { color: #059669; }
.summary-card.danger strong { color: #dc2626; }
.task-panel { overflow: hidden; padding: 16px; border: 1px solid #e7ebf1; border-radius: 14px; background: var(--app-surface); }
.task-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.task-toolbar :deep(.el-input) { width: min(360px, 100%); }
.task-toolbar :deep(.el-select) { width: 160px; }
.auto-refresh { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; color: #2563eb; font-size: 12px; }
.auto-refresh i { width: 7px; height: 7px; border-radius: 50%; background: #2563eb; box-shadow: 0 0 0 4px rgba(37, 99, 235, .12); }
.task-title, .task-description { display: block; }
.task-title { color: var(--app-text); font-size: 13px; }
.task-description { margin-top: 4px; color: $text-secondary; font-size: 12px; }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } .task-toolbar { align-items: stretch; flex-wrap: wrap; } .auto-refresh { width: 100%; margin-left: 0; } }
@media (max-width: 560px) { .summary-grid { grid-template-columns: 1fr; } .task-toolbar :deep(.el-input), .task-toolbar :deep(.el-select) { width: 100%; } }
</style>
