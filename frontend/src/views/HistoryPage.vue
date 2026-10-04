<template>
  <div class="frontend-b-page">
    <ModulePageHeader
      :title="text.title"
    >
      <el-button :icon="Download" :loading="exporting" @click="exportHistory">{{ text.export }}</el-button>
      <el-button :icon="Refresh" :loading="loading" @click="loadHistory">
        {{ text.refresh }}
      </el-button>
    </ModulePageHeader>

    <PageErrorAlert
      v-if="pageError"
      :message="pageError"
      :retry-text="text.reload"
      @retry="loadHistory"
    />

    <section class="filter-bar">
      <div v-if="false" class="filter-bar__title">
        <el-icon><Filter /></el-icon>
        <span>{{ text.filterTitle }}</span>
      </div>
      <el-select v-if="false" v-model="filters.sceneId" :placeholder="text.allScenes" clearable>
        <el-option
          v-for="scene in scenes"
          :key="scene.id"
          :label="sceneLabel(scene)"
          :value="scene.id"
        />
      </el-select>
      <el-select v-model="filters.mediaType" :placeholder="text.allTypes" clearable>
        <el-option
          v-for="option in mediaTypeOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-select v-if="false" v-model="filters.status" :placeholder="text.allStatuses" clearable>
        <el-option
          v-for="option in statusOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-date-picker
        v-model="filters.dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        :start-placeholder="text.startDate"
        :end-placeholder="text.endDate"
      />
      <el-button type="primary" :icon="Search" @click="applyFilters">{{ text.search }}</el-button>
      <el-button @click="resetFilters">{{ text.reset }}</el-button>
    </section>

    <section class="history-card">
      <div class="history-bulk-toolbar">
        <el-button text size="small" @click="bulkMode = !bulkMode">{{ bulkMode ? '退出批量' : '批量操作' }}</el-button>
        <el-button v-if="bulkMode" size="small" :disabled="!selectedRows.length" @click="exportHistory">{{ text.export }}</el-button>
        <el-button v-if="bulkMode" type="danger" plain size="small" :disabled="!selectedRows.length" @click="removeSelected">删除所选</el-button>
      </div>
      <el-table
        v-loading="loading"
        :data="history.items"
        row-key="id"
        :empty-text="text.emptyHistory"
        @selection-change="selectedRows = $event"
      >
        <el-table-column v-if="bulkMode" type="selection" width="48" />
        <el-table-column prop="id" :label="text.taskId" width="92" />
        <el-table-column :label="text.scene" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ displayScene(row.sceneName) }}</template>
        </el-table-column>
        <el-table-column :label="text.taskType" width="112">
          <template #default="{ row }">{{ taskTypeLabel(row.taskType) }}</template>
        </el-table-column>
        <el-table-column :label="text.status" width="105">
          <template #default="{ row }">
            <StatusTag :status="row.status" :label="statusLabel(row.status)" round>
              {{ statusLabel(row.status) }}
            </StatusTag>
          </template>
        </el-table-column>
        <el-table-column :label="text.images" width="100" align="right"><template #default="{ row }">{{ row.totalImages }}{{ row.taskType === 'video' ? '帧' : '张' }}</template></el-table-column>
        <el-table-column prop="totalObjects" :label="text.defects" width="82" align="right" />
        <el-table-column :label="text.duration" width="110" align="right">
          <template #default="{ row }">{{ formatHistoryDuration(row.totalInferenceTimeMs) }}</template>
        </el-table-column>
        <el-table-column :label="text.createdAt" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column :label="text.actions" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">
              {{ text.detail }}
            </el-button>
            <el-button
              link
              type="danger"
              :icon="Delete"
              :loading="deletingId === row.id"
              @click="removeHistory(row)"
            >
              {{ text.delete }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="history.total > 0"
        class="history-pagination"
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="history.total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadHistory"
        @size-change="handlePageSizeChange"
      />
    </section>

    <el-drawer v-model="detailVisible" :title="text.detailTitle" size="min(720px, 92vw)">
      <div v-loading="detailLoading" class="detail-content">
        <el-alert
          v-if="detailError"
          :title="detailError"
          type="error"
          show-icon
          :closable="false"
        />

        <template v-if="detail.task && !detailError">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="text.taskId">{{ detail.task.publicTaskId }}</el-descriptions-item>
            <el-descriptions-item :label="text.status">
              <StatusTag :status="detail.task.status" :label="statusLabel(detail.task.status)">
                {{ statusLabel(detail.task.status) }}
              </StatusTag>
            </el-descriptions-item>
            <el-descriptions-item :label="text.scene">{{ displayScene(detail.task.sceneName) }}</el-descriptions-item>
            <el-descriptions-item :label="text.taskType">{{ taskTypeLabel(detail.task.taskType) }}</el-descriptions-item>
            <el-descriptions-item :label="text.imageCount">{{ detail.task.totalImages }}</el-descriptions-item>
            <el-descriptions-item :label="text.defectCount">{{ detail.task.totalObjects }}</el-descriptions-item>
            <el-descriptions-item :label="text.confThreshold">{{ formatNumber(detail.task.confThreshold, 2) }}</el-descriptions-item>
            <el-descriptions-item label="IoU 阈值">{{ formatNumber(detail.task.iouThreshold, 2) }}</el-descriptions-item>
            <el-descriptions-item :label="text.totalInference">{{ formatHistoryDuration(detail.task.totalInferenceTimeMs) }}</el-descriptions-item>
            <el-descriptions-item :label="text.avgInference">{{ formatHistoryDuration(detail.task.avgInferenceTimeMs) }}</el-descriptions-item>
            <el-descriptions-item :label="text.createdAt">{{ formatDateTime(detail.task.createdAt) }}</el-descriptions-item>
            <el-descriptions-item :label="text.completedAt">{{ formatDateTime(detail.task.completedAt) }}</el-descriptions-item>
          </el-descriptions>

          <el-alert
            v-if="detail.task.errorMessage"
            class="detail-error"
            :title="text.taskError"
            :description="detail.task.errorMessage"
            type="error"
            show-icon
            :closable="false"
          />

          <div class="result-heading">
            <h3>{{ text.defectDetails }}</h3>
            <span>{{ text.resultCount(detail.results.length) }}</span>
          </div>
          <el-table :data="detail.results" :empty-text="text.emptyDetail" max-height="430">
            <el-table-column :label="text.resultImage" width="84">
              <template #default="{ row }">
                <el-image
                  v-if="row.annotatedImageUrl"
                  class="result-image"
                  :src="row.annotatedImageUrl"
                  :preview-src-list="[row.annotatedImageUrl]"
                  preview-teleported
                  fit="cover"
                />
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column :label="text.file" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ fileName(row.imagePath) }}</template>
            </el-table-column>
            <el-table-column :label="text.defectClass" width="110">
              <template #default="{ row }">{{ displayDefect(row.classNameCn) }}</template>
            </el-table-column>
            <el-table-column :label="text.confidence" width="92" align="right">
              <template #default="{ row }">{{ formatPercent(row.confidence) }}</template>
            </el-table-column>
            <el-table-column :label="text.bbox" min-width="150">
              <template #default="{ row }">{{ formatBbox(row.bbox) }}</template>
            </el-table-column>
          </el-table>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { Delete, Download, Filter, Refresh, Search, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { useSettingsStore } from '@/stores/settings'
import {
  HISTORY_TASK_TYPE_OPTIONS,
  deleteHistoryApi,
  getHistoryTaskTypeLabel,
  getHistoryApi,
  getHistoryDetailApi,
  exportHistoryApi,
} from "@/api/history";
import { getScenesApi } from "@/api/models";
import ModulePageHeader from "@/components/common/ModulePageHeader.vue";
import PageErrorAlert from "@/components/common/PageErrorAlert.vue";
import StatusTag from "@/components/common/StatusTag.vue";
import { getApiErrorMessage } from "@/utils/apiError";
import { displayDefectName, displaySceneName } from "@/utils/displayText";

const settingsStore = useSettingsStore()
const exporting = ref(false)
const route = useRoute()
const taskTypeOptions = computed(() => HISTORY_TASK_TYPE_OPTIONS.map((item) => ({
  ...item,
  label: taskTypeLabel(item.value),
})));
const mediaTypeOptions = [
  { value: '', label: '全部' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
]
const statusOptions = computed(() => [
  { value: "pending", label: text.value.pending },
  { value: "processing", label: text.value.processing },
  { value: "completed", label: text.value.completed },
  { value: "failed", label: text.value.failed },
]);

const text = computed(() => settingsStore.isEnglish ? {
  title: 'History',
  refresh: 'Refresh',
  export: 'Export CSV',
  reload: 'Reload',
  filterTitle: 'Filters',
  allScenes: 'All scenes',
  allTypes: 'All types',
  allStatuses: 'All statuses',
  startDate: 'Start date',
  endDate: 'End date',
  search: 'Search',
  reset: 'Reset',
  emptyHistory: 'No detection records for the current filters',
  taskId: 'Task ID',
  scene: 'Scene',
  taskType: 'Type',
  status: 'Status',
  images: 'Images',
  defects: 'Defects',
  duration: 'Duration',
  createdAt: 'Created at',
  actions: 'Actions',
  detail: 'Details',
  delete: 'Delete',
  detailTitle: 'Detection Task Details',
  imageCount: 'Images',
  defectCount: 'Defects',
  confThreshold: 'Confidence threshold',
  totalInference: 'Total inference time',
  avgInference: 'Average image time',
  completedAt: 'Completed at',
  taskError: 'Task error',
  defectDetails: 'Defect Details',
  resultCount: (count) => `${count} target records`,
  emptyDetail: 'No defect target details for this task',
  resultImage: 'Result',
  file: 'File',
  defectClass: 'Class',
  confidence: 'Confidence',
  bbox: 'Bbox',
  pending: 'Pending',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
  single: 'Single image',
  batch: 'Batch',
  zip: 'ZIP',
  video: 'Video',
  camera: 'Camera',
  sceneFailed: 'Failed to load detection scenes',
  historyFailed: 'Failed to load history',
  detailFailed: 'Failed to load detection details',
  deleteTitle: 'Delete history record',
  deleteConfirm: (id) => `Delete detection task #${id}? Related results will also be deleted.`,
  deleteSuccess: 'History record deleted',
  deleteFailed: 'Failed to delete history record',
} : {
  title: '历史记录',
  refresh: '刷新',
  reload: '重新加载',
  filterTitle: '记录筛选',
  allScenes: '全部场景',
  allTypes: '全部类型',
  allStatuses: '全部状态',
  startDate: '开始日期',
  endDate: '结束日期',
  search: '查询',
  reset: '重置',
  emptyHistory: '当前筛选条件下暂无检测记录',
  taskId: '任务 ID',
  scene: '检测场景',
  taskType: '检测类型',
  status: '状态',
  images: '图片',
  defects: '缺陷',
  duration: '总耗时',
  createdAt: '创建时间',
  actions: '操作',
  detail: '详情',
  delete: '删除',
  detailTitle: '检测任务详情',
  imageCount: '图片数量',
  defectCount: '缺陷数量',
  confThreshold: '置信度阈值',
  totalInference: '总推理耗时',
  avgInference: '单图平均耗时',
  completedAt: '完成时间',
  taskError: '任务错误信息',
  defectDetails: '缺陷明细',
  resultCount: (count) => `共 ${count} 条目标记录`,
  emptyDetail: '该任务没有缺陷目标明细',
  resultImage: '结果图',
  file: '文件',
  defectClass: '缺陷类别',
  confidence: '置信度',
  bbox: '边界框',
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  single: '单图检测',
  batch: '批量检测',
  zip: 'ZIP 检测',
  video: '视频检测',
  camera: '摄像头',
  sceneFailed: '检测场景加载失败',
  historyFailed: '历史记录加载失败',
  detailFailed: '检测详情加载失败',
  deleteTitle: '删除历史记录',
  deleteConfirm: (id) => `确定删除检测任务 #${id} 吗？相关结果记录也会被删除。`,
  deleteSuccess: '历史记录已删除',
  deleteFailed: '历史记录删除失败',
})

const loading = ref(false);
const pageError = ref("");
const scenes = ref([]);
const deletingId = ref(null);
const filters = reactive({ sceneId: "", taskType: "", status: "", mediaType: "", keyword: "", ownerUserId: "", dateRange: [] });
const pagination = reactive({ page: 1, pageSize: 20 });
const history = reactive({ items: [], total: 0 });
const bulkMode = ref(false)
const selectedRows = ref([])

const detailVisible = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const detail = reactive({ task: null, results: [] });

function taskTypeLabel(value) {
  const cnLabel = getHistoryTaskTypeLabel(value);
  if (!settingsStore.isEnglish) return cnLabel;
  return {
    single: text.value.single,
    batch: text.value.batch,
    zip: text.value.zip,
    video: text.value.video,
    camera: text.value.camera,
  }[value] || value || "—";
}

function sceneLabel(scene) {
  return displaySceneName(scene.displayName || scene.name, settingsStore.isEnglish);
}

function displayScene(name) {
  return displaySceneName(name, settingsStore.isEnglish);
}

function displayDefect(name) {
  return displayDefectName(name, settingsStore.isEnglish);
}

function statusLabel(value) {
  return statusOptions.value.find((item) => item.value === value)?.label || value || "—";
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(settingsStore.isEnglish ? "en-US" : "zh-CN", { hour12: false });
}

function formatHistoryDuration(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number >= 1000 ? `${(number / 1000).toFixed(2)}s` : `${Math.round(number)}ms`;
}

function formatDuration(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)} ms` : "—";
}

function formatNumber(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "—";
}

function formatBbox(value) {
  return Array.isArray(value) && value.length === 4
    ? value.map((item) => Number(item).toFixed(0)).join(", ")
    : "—";
}

function fileName(path) {
  return path?.split(/[\\/]/).pop() || "—";
}

async function loadScenes() {
  try {
    scenes.value = await getScenesApi();
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.sceneFailed);
  }
}

async function loadHistory() {
  loading.value = true;
  pageError.value = "";
  try {
    const data = await getHistoryApi({
      sceneId: filters.sceneId,
      taskType: filters.taskType,
      status: filters.status,
      mediaType: filters.mediaType,
      keyword: filters.keyword,
      ownerUserId: filters.ownerUserId,
      startDate: filters.dateRange?.[0],
      endDate: filters.dateRange?.[1],
      page: pagination.page,
      pageSize: pagination.pageSize,
    });
    history.items = data.items;
    history.total = data.total;
  } catch (error) {
    history.items = [];
    history.total = 0;
    pageError.value = getApiErrorMessage(error, text.value.historyFailed);
  } finally {
    loading.value = false;
  }
}

async function exportHistory() {
  exporting.value = true
  try {
    const blob = await exportHistoryApi({ mediaType: filters.mediaType, startDate: filters.dateRange?.[0], endDate: filters.dateRange?.[1] })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = 'detection-history.csv'; link.click(); URL.revokeObjectURL(url)
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.historyFailed)
  } finally { exporting.value = false }
}

function applyFilters() {
  pagination.page = 1;
  loadHistory();
}

function resetFilters() {
  Object.assign(filters, { sceneId: "", taskType: "", status: "", mediaType: "", keyword: "", ownerUserId: "", dateRange: [] });
  selectedRows.value = []
  pagination.page = 1;
  loadHistory();
}

function handlePageSizeChange() {
  pagination.page = 1;
  loadHistory();
}

async function openDetail(row) {
  detailVisible.value = true;
  detailLoading.value = true;
  detailError.value = "";
  detail.task = null;
  detail.results = [];
  try {
    Object.assign(detail, await getHistoryDetailApi(row.id));
  } catch (error) {
    detailError.value = getApiErrorMessage(error, text.value.detailFailed);
  } finally {
    detailLoading.value = false;
  }
}

async function removeSelected() {
  if (!selectedRows.value.length) return
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selectedRows.value.length} 条记录吗？`, text.value.deleteTitle, { type: 'warning' })
    for (const row of selectedRows.value) await deleteHistoryApi(row.id)
    selectedRows.value = []
    await loadHistory()
  } catch { /* cancel */ }
}

async function removeHistory(row) {
  try {
    await ElMessageBox.confirm(
      text.value.deleteConfirm(row.publicTaskId),
      text.value.deleteTitle,
      { type: "warning", confirmButtonText: text.value.delete, cancelButtonText: text.value.reset },
    );
    deletingId.value = row.id;
    await deleteHistoryApi(row.id);
    ElMessage.success(text.value.deleteSuccess);
    if (history.items.length === 1 && pagination.page > 1) pagination.page -= 1;
    await loadHistory();
  } catch (error) {
    if (error !== "cancel" && error !== "close") {
      pageError.value = getApiErrorMessage(error, text.value.deleteFailed);
    }
  } finally {
    deletingId.value = null;
  }
}

onMounted(async () => {
  Object.assign(filters, {
    sceneId: "",
    taskType: "",
    status: "",
    mediaType: route.query.media_type || "",
    keyword: route.query.keyword || "",
    ownerUserId: route.query.owner_user_id || "",
  })
  await Promise.all([loadScenes(), loadHistory()]);
  const taskId = Number(route.query.task);
  if (Number.isInteger(taskId) && taskId > 0) await openDetail({ id: taskId });
});
</script>

<style lang="scss" scoped>
.frontend-b-page { min-height: 100%; max-width: 1200px; margin: 0 auto; padding: 0; }
.page-alert { margin-bottom: 16px; }
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; padding: 14px 16px; border: 1px solid #e7ebf1; border-radius: 12px; background: #fff; }
.history-bulk-toolbar { display: flex; justify-content: flex-end; gap: 8px; margin: 0 0 8px; }
.filter-bar__title { display: flex; align-items: center; gap: 7px; margin-right: auto; color: #344054; font-weight: 600; }
.filter-bar :deep(.el-select) { width: 160px; }
.history-card { overflow: hidden; padding: 8px 16px 16px; border: 1px solid #e7ebf1; border-radius: 14px; background: #fff; box-shadow: 0 8px 24px rgba(28, 39, 60, 0.05); }
.history-pagination { justify-content: flex-end; margin-top: 16px; }
.detail-content { min-height: 180px; }
.detail-error { margin-top: 16px; }
.result-heading { display: flex; align-items: baseline; justify-content: space-between; margin: 24px 0 12px; }
.result-heading h3 { margin: 0; color: #1f2937; font-size: 16px; }
.result-heading span { color: $text-secondary; font-size: 12px; }
.result-image { width: 54px; height: 42px; border-radius: 6px; }
@media (max-width: 900px) { .filter-bar { flex-wrap: wrap; } .filter-bar__title { width: 100%; } .filter-bar :deep(.el-select) { flex: 1; min-width: 140px; } }
</style>
