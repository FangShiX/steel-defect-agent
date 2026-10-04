<template>
  <div class="training-page">
    <ModulePageHeader :title="text.title">
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        {{ text.newTask }}
      </el-button>
    </ModulePageHeader>

    <PageErrorAlert
      v-if="pageError"
      :message="pageError.message"
      :retry-text="text.retry"
      closable
      @retry="retryPageAction"
      @close="pageError = null"
    />

    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <span class="card-title">{{ text.taskList }}</span>
            <span class="card-caption">{{ text.taskCount(taskList.length) }}</span>
          </div>
          <div class="section-header-actions">
            <el-button text :loading="loadingTasks" @click="fetchTasks"><el-icon><Refresh /></el-icon>{{ text.refresh }}</el-button>
            <el-button text @click="taskExpanded = !taskExpanded">{{ taskExpanded ? '收起' : '展开' }}</el-button>
          </div>
        </div>
      </template>

      <div v-if="taskExpanded">
      <el-table
        v-loading="loadingTasks"
        :data="taskList"
        row-key="id"
        stripe
        :empty-text="text.emptyTasks"
        highlight-current-row
        @current-change="handleCurrentTaskChange"
      >
        <template #empty>
          <el-empty :description="text.emptyTasks">
            <el-button type="primary" @click="showCreateDialog = true">{{ text.newTask }}</el-button>
          </el-empty>
        </template>
        <el-table-column :label="text.taskId" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.public_task_id || row.task_uuid }}</template>
        </el-table-column>
        <el-table-column prop="model_name" :label="text.model" min-width="106" />
        <el-table-column :label="text.dataset" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDataset(row) }}</template>
        </el-table-column>
        <el-table-column prop="device" :label="text.device" min-width="82" />
        <el-table-column :label="text.progress" min-width="188">
          <template #default="{ row }">
            <el-progress
              :percentage="normalizeProgress(row.progress)"
              :status="progressStatus(row.status)"
              :stroke-width="14"
            />
          </template>
        </el-table-column>
        <el-table-column :label="text.epoch" min-width="96">
          <template #default="{ row }">
            {{ row.current_epoch || 0 }}/{{ row.epochs || 0 }}
          </template>
        </el-table-column>
        <el-table-column :label="text.status" min-width="96">
          <template #default="{ row }">
            <StatusTag :status="row.status" :label="statusText(row.status)" size="small">
              {{ statusText(row.status) }}
            </StatusTag>
          </template>
        </el-table-column>
        <el-table-column :label="text.createdAt" min-width="168">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column :label="text.actions" min-width="148" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" text @click.stop="selectTask(row)">
              {{ text.monitor }}
            </el-button>
            <el-button
              v-if="row.status === 'running'"
              size="small"
              type="danger"
              text
              @click.stop="stopTask(taskIdentifier(row))"
            >
              {{ text.stop }}
            </el-button>
            <el-button
              v-if="row.status === 'failed' || row.status === 'cancelled'"
              size="small"
              type="warning"
              text
              @click.stop="retryTask(row)"
            >
              {{ text.retry }}
            </el-button>
            <el-button
              v-if="isDeletable(row)"
              size="small"
              type="danger"
              text
              @click.stop="deleteTask(row)"
            >
              {{ text.delete }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </el-card>

    <el-card v-if="false" class="section-card dataset-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div><span class="card-title">{{ bilingual('训练数据集管理', 'Training datasets') }}</span><span class="card-caption">{{ bilingual('仅可删除自己上传且未被任务使用的数据集', 'Only unused datasets uploaded by you can be deleted') }}</span></div>
          <el-button text :loading="loadingDatasets" @click="fetchDatasets"><el-icon><Refresh /></el-icon>{{ text.refresh }}</el-button>
        </div>
      </template>
      <el-table :data="datasets" size="small" stripe :empty-text="bilingual('暂无数据集', 'No datasets')">
        <el-table-column prop="name" :label="bilingual('名称', 'Name')" min-width="180" show-overflow-tooltip />
        <el-table-column prop="path" :label="bilingual('路径', 'Path')" min-width="180" show-overflow-tooltip />
        <el-table-column :label="bilingual('状态', 'Status')" width="110">
          <template #default="{ row }"><el-tag size="small" :type="row.ready ? 'success' : 'warning'">{{ row.ready ? bilingual('可训练', 'Ready') : bilingual('待校验', 'Pending') }}</el-tag></template>
        </el-table-column>
        <el-table-column :label="bilingual('操作', 'Actions')" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_builtin" text type="danger" size="small" @click="deleteDataset(row)">{{ text.delete }}</el-button>
            <span v-else class="form-hint">{{ bilingual('内置', 'Built-in') }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <FileBrowserPage embedded />

    <el-card v-if="selectedTask && monitorExpanded" class="section-card" shadow="never">
      <template #header>
        <div class="card-header monitor-header">
          <div>
            <span class="card-title">{{ text.trainingMonitor }} - {{ text.task }} {{ selectedTask.public_task_id || selectedTask.task_uuid }}</span>
            <el-tag :type="statusType(selectedTask.status)" size="small">
              {{ statusText(selectedTask.status) }}
            </el-tag>
          </div>
          <div class="monitor-info">
            <span>{{ text.model }}: {{ selectedTask.model_name }}</span>
            <span>{{ text.dataset }}: {{ formatDataset(selectedTask) }}</span>
            <span>{{ text.device }}: {{ selectedTask.device }}</span>
            <span>{{ text.epoch }}：{{ selectedTask.current_epoch || 0 }}/{{ selectedTask.epochs || 0 }}</span>
          </div>
          <el-button text class="monitor-toggle" @click="monitorExpanded = false">
            {{ monitorExpanded ? '收起监控' : '展开监控' }}
          </el-button>
        </div>
      </template>

      <div class="monitor-body">
      <PageErrorAlert
      v-if="monitorError"
      class="monitor-alert"
      :message="monitorError.message"
      :retry-text="text.retry"
      @retry="retryMonitorAction"
      />
    <PageErrorAlert
      v-if="selectedTask.status === 'failed' && selectedTask.error_message"
      class="monitor-alert"
      :message="selectedTask.error_message"
      :retry-text="text.retry"
      @retry="retryTask(selectedTask)"
    />

      <el-progress
        class="monitor-progress"
        :percentage="normalizeProgress(selectedTask.progress)"
        :status="progressStatus(selectedTask.status)"
        :stroke-width="18"
      />

      <el-row :gutter="16" class="metric-grid">
        <el-col
          v-for="item in metricCards"
          :key="item.label"
          :xs="12"
          :sm="8"
          :lg="4"
        >
          <div class="metric-item">
            <div class="metric-value">{{ item.value }}</div>
            <div class="metric-label">{{ item.label }}</div>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="chart-grid">
        <el-col :xs="24" :lg="12">
          <div ref="lossChartRef" class="chart-panel" />
        </el-col>
        <el-col :xs="24" :lg="12">
          <div ref="mapChartRef" class="chart-panel" />
        </el-col>
      </el-row>
      </div>
    </el-card>

    <el-card
      v-if="selectedTask && monitorExpanded && selectedTask.status === 'completed'"
      class="section-card"
      shadow="never"
    >
      <template #header>
        <div class="card-header">
          <div>
            <span class="card-title">{{ text.modelActions }}</span>
          </div>
        </div>
      </template>

      <el-space wrap>
        <el-button type="primary" :loading="validating" @click="validateModel">
          {{ text.evaluate }}
        </el-button>
        <el-button :loading="downloading" @click="downloadModel">{{ text.downloadWeights }}</el-button>
        <el-dropdown trigger="click">
          <el-button>更多操作<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="showExportDialog = true">{{ text.exportModel }}</el-dropdown-item>
              <el-dropdown-item @click="downloadReport">{{ text.exportReport }}</el-dropdown-item>
              <el-dropdown-item @click="openPredictDialog">{{ text.testValidate }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-space>
    </el-card>

    <el-card v-if="evalReport" class="section-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <span class="card-title">{{ text.evaluationReport }}</span>
            <el-tag size="small">
              {{ evalReport.split === 'test' ? text.testSet : text.validationSet }}
            </el-tag>
          </div>
          <span class="card-caption">模型版本 {{ evalReport.model_version || '-' }}</span>
        </div>
      </template>

      <el-row :gutter="16" class="metric-grid evaluation-metrics">
        <el-col
          v-for="item in evalMetricCards"
          :key="item.label"
          :xs="12"
          :sm="6"
        >
          <div class="metric-item">
            <div class="metric-value" :style="{ color: item.color }">{{ item.value }}</div>
            <div class="metric-label">{{ item.label }}</div>
          </div>
        </el-col>
      </el-row>

      <div class="subsection-title">{{ text.perClassAp }}</div>
      <el-table
        :data="perClassData"
        stripe
        :row-class-name="tableRowClassName"
        empty-text="评估报告中暂无分类指标"
      >
        <el-table-column prop="class_name" :label="text.className" min-width="180" />
        <el-table-column label="AP@50" min-width="140">
          <template #default="{ row }">
            <span :class="{ 'weak-value': row.ap50 < 0.5 }">
              {{ formatPercent(row.ap50) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="AP@50-95" min-width="140">
          <template #default="{ row }">{{ formatPercent(row.ap50_95) }}</template>
        </el-table-column>
        <el-table-column :label="text.evaluation" min-width="120">
          <template #default="{ row }">
            <el-tag :type="apLevel(row.ap50).type" size="small">
              {{ apLevel(row.ap50).text }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>

      <el-row v-if="evalReport.visualization" :gutter="16" class="chart-grid evaluation-charts">
        <el-col :xs="24" :lg="8"><div ref="confusionChartRef" class="chart-panel" /></el-col>
        <el-col :xs="24" :lg="8"><div ref="prChartRef" class="chart-panel" /></el-col>
        <el-col :xs="24" :lg="8"><div ref="f1ChartRef" class="chart-panel" /></el-col>
      </el-row>
    </el-card>

    <el-dialog
      v-model="showCreateDialog"
      :title="bilingual('新建训练任务', 'New training task')"
      width="min(620px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="trainForm" label-width="110px">
        <el-form-item :label="bilingual('训练数据集', 'Training dataset')">
          <div class="dataset-picker">
            <el-select v-model="trainForm.dataset_path" class="full-width" :placeholder="bilingual('选择已准备的数据集', 'Select a prepared dataset')">
              <el-option
                v-for="dataset in datasets"
                :key="dataset.path || dataset.name"
                :label="dataset.name"
                :value="dataset.path"
                :disabled="!dataset.ready || dataset.status === 'archived'"
              />
            </el-select>
            <el-upload
              :show-file-list="false"
              accept=".zip"
              :auto-upload="false"
              :on-change="handleDatasetUpload"
            >
              <el-button :loading="uploadingDataset" :icon="UploadFilled">{{ bilingual('上传 ZIP', 'Upload ZIP') }}</el-button>
            </el-upload>
          </div>
          <span class="form-hint">{{ bilingual('ZIP 根目录必须包含 data.yaml', 'The ZIP root must contain data.yaml') }}</span>
        </el-form-item>
        <el-form-item :label="bilingual('检测场景', 'Detection scene')">
          <el-select v-model="trainForm.scene_id" class="full-width" :placeholder="bilingual('选择场景', 'Select a scene')">
            <el-option
              v-for="scene in scenes"
              :key="scene.id"
              :label="scene.displayName || scene.name"
              :value="Number(scene.id)"
            />
          </el-select>
        </el-form-item>

        <el-form-item :label="bilingual('基础模型', 'Base model')">
          <el-select v-model="trainForm.model_name" class="full-width">
            <el-option label="YOLO11n (Nano，最快)" value="yolo11n" />
            <el-option label="YOLO11s (Small)" value="yolo11s" />
            <el-option label="YOLO11m (Medium)" value="yolo11m" />
            <el-option label="YOLO11l (Large)" value="yolo11l" />
            <el-option label="YOLO11x (XLarge，精度优先)" value="yolo11x" />
          </el-select>
        </el-form-item>

        <el-form-item :label="bilingual('训练轮数', 'Epochs')">
          <el-slider v-model="trainForm.epochs" :min="10" :max="500" :step="10" show-input />
        </el-form-item>

        <el-form-item :label="bilingual('批次大小', 'Batch size')">
          <el-input-number v-model="trainForm.batch_size" :min="1" :max="64" :step="1" />
        </el-form-item>

        <el-form-item :label="bilingual('图像尺寸', 'Image size')">
          <el-select v-model="trainForm.img_size" class="full-width">
            <el-option label="416" :value="416" />
            <el-option label="512" :value="512" />
            <el-option label="640（默认）" :value="640" />
            <el-option label="768" :value="768" />
          </el-select>
        </el-form-item>

        <el-form-item :label="bilingual('训练设备', 'Device')">
          <el-radio-group v-model="trainForm.device">
            <el-radio value="cpu">CPU（本地）</el-radio>
            <el-radio value="0">GPU:0</el-radio>
            <el-radio value="1">GPU:1</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item :label="bilingual('优化器', 'Optimizer')">
          <el-select v-model="trainForm.optimizer" class="full-width">
            <el-option label="SGD（推荐）" value="SGD" />
            <el-option label="Adam" value="Adam" />
            <el-option label="AdamW" value="AdamW" />
          </el-select>
        </el-form-item>

        <el-form-item :label="bilingual('初始学习率', 'Initial learning rate')">
          <el-input-number
            v-model="trainForm.lr0"
            :min="0.0001"
            :max="0.1"
            :step="0.001"
            :precision="4"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">{{ bilingual('取消', 'Cancel') }}</el-button>
        <el-button type="primary" :loading="creating" @click="createTask">
          {{ bilingual('启动训练', 'Start training') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showExportDialog"
      :title="bilingual('导出模型', 'Export model')"
      width="min(520px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="exportForm" label-width="100px">
        <el-form-item :label="bilingual('版本号', 'Version')">
          <el-input v-model="exportForm.version" placeholder="留空则自动生成，如 v1.0.0" />
        </el-form-item>
        <el-form-item :label="bilingual('版本描述', 'Description')">
          <el-input
            v-model="exportForm.description"
            type="textarea"
            :rows="3"
            placeholder="描述本次训练的主要变更"
          />
        </el-form-item>
        <el-form-item :label="bilingual('设为默认', 'Set as default')">
          <el-switch v-model="exportForm.set_default" />
          <span class="form-hint">设为该场景的默认检测模型</span>
        </el-form-item>
        <el-form-item :label="bilingual('上传 MinIO', 'Upload to MinIO')">
          <el-switch v-model="exportForm.upload_minio" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showExportDialog = false">{{ bilingual('取消', 'Cancel') }}</el-button>
        <el-button type="primary" :loading="exporting" @click="exportModel">
          {{ bilingual('确认导出', 'Confirm export') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showPredictDialog"
      :title="bilingual('测试图验证', 'Test image validation')"
      width="min(980px, 94vw)"
      :close-on-click-modal="false"
      @closed="disposePredictChart"
    >
      <el-row :gutter="20">
        <el-col :xs="24" :md="10">
          <el-upload
            drag
            action=""
            :auto-upload="false"
            :on-change="handlePredictFileChange"
            :limit="1"
            accept="image/jpeg,image/png,image/bmp,image/webp"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div>拖拽图片到此处，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 JPG、PNG、BMP、WebP 格式</div>
            </template>
          </el-upload>

          <el-form label-width="72px" class="predict-settings">
            <el-form-item label="置信度">
              <el-slider
                v-model="predictConf"
                :min="0.05"
                :max="0.95"
                :step="0.05"
                show-input
              />
            </el-form-item>
            <el-form-item label="IoU">
              <el-slider
                v-model="predictIou"
                :min="0.1"
                :max="0.9"
                :step="0.05"
                show-input
              />
            </el-form-item>
          </el-form>

          <el-button
            class="full-width"
            type="primary"
            :loading="predicting"
            :disabled="!predictFile"
            @click="runPredict"
          >
            开始检测
          </el-button>
        </el-col>

        <el-col :xs="24" :md="14">
          <div v-if="predictResult" class="predict-result">
            <img
              :src="annotatedImageSrc"
              class="annotated-image"
              alt="模型测试验证标注结果"
            />
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="检测目标数">
                {{ predictResult.total_objects }}
              </el-descriptions-item>
              <el-descriptions-item label="推理耗时">
                {{ predictResult.inference_time }} ms
              </el-descriptions-item>
            </el-descriptions>
            <div ref="predictChartRef" class="predict-chart" />
            <el-table :data="predictResult.detections || []" stripe size="small" max-height="210">
              <el-table-column prop="class_name" label="类别" min-width="110" />
              <el-table-column label="置信度" min-width="96">
                <template #default="{ row }">{{ formatPercent(row.confidence) }}</template>
              </el-table-column>
              <el-table-column label="位置" min-width="180">
                <template #default="{ row }">{{ formatBoundingBox(row.bbox) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else description="上传一张全新测试图片并点击检测" />
        </el-col>
      </el-row>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '@/stores/settings'
import { useTaskStore } from '@/stores/tasks'
import { ArrowDown, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import {
  downloadTrainingModel,
  downloadTrainingReport,
  deleteTrainingTask,
  exportTrainingModel,
  getTrainingDatasets,
  getTrainingMetrics,
  getTrainingStatus,
  predictTrainingImage,
  retryTrainingTask,
  startTraining,
  stopTraining,
  uploadTrainingDataset,
  deleteTrainingDataset,
  validateTrainingModel,
} from '@/api/training'
import { getScenesApi } from '@/api/models'
import FileBrowserPage from '@/views/FileBrowserPage.vue'
import ModulePageHeader from '@/components/common/ModulePageHeader.vue'
import PageErrorAlert from '@/components/common/PageErrorAlert.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { getApiErrorInfo } from '@/utils/apiError'

const POLL_INTERVAL = 5000
const RUNNING_STATUSES = new Set(['pending', 'running'])
const settingsStore = useSettingsStore()
const route = useRoute()
const taskStore = useTaskStore()
const reportDownloading = ref(false)

const text = computed(() => settingsStore.isEnglish ? {
  title: 'Model Training & Monitoring',
  newTask: 'New training task',
  taskList: 'Training tasks',
  taskCount: (count) => `${count} tasks`,
  refresh: 'Refresh',
  emptyTasks: 'No training tasks',
  taskId: 'Task ID',
  model: 'Model',
  dataset: 'Dataset',
  device: 'Device',
  progress: 'Progress',
  status: 'Status',
  createdAt: 'Created at',
  actions: 'Actions',
  monitor: 'Monitor',
  stop: 'Stop',
  delete: 'Delete',
  task: 'Task',
  trainingMonitor: 'Training Monitor',
  modelActions: 'Model Actions',
  evaluate: 'Evaluate model',
  exportModel: 'Export model',
  downloadWeights: 'Download weights',
  exportReport: 'Export report',
  testValidate: 'Test validation',
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  excellent: 'Excellent',
  good: 'Good',
  improve: 'Needs work',
  epoch: 'Epoch',
  boxLoss: 'Box Loss',
  clsLoss: 'Cls Loss',
  precision: 'Precision',
  recall: 'Recall',
  evaluationReport: 'Evaluation report',
  validationSet: 'Validation set',
  testSet: 'Test set',
  perClassAp: 'Per-class AP analysis',
  className: 'Class',
  evaluation: 'Evaluation',
  confusionMatrix: 'Confusion Matrix',
  prCurve: 'PR Curve',
  f1Curve: 'F1 Curve',
  dateLocale: 'en-US',
  fetchTasksFailed: 'Failed to load training tasks',
  fetchDatasetsFailed: 'Failed to load training datasets',
  retry: 'Retry',
  deleteSuccess: 'Training history task deleted',
} : {
  title: '模型训练与管理',
  newTask: '新建训练任务',
  taskList: '训练任务列表',
  taskCount: (count) => `共 ${count} 个任务`,
  refresh: '刷新',
  emptyTasks: '暂无训练任务',
  taskId: '任务 ID',
  model: '模型',
  dataset: '数据集',
  device: '设备',
  progress: '进度',
  status: '状态',
  createdAt: '创建时间',
  actions: '操作',
  monitor: '监控',
  stop: '停止',
  delete: '删除',
  task: '任务',
  trainingMonitor: '训练监控',
  modelActions: '模型操作',
  evaluate: '评估模型',
  exportModel: '导出模型',
  downloadWeights: '下载权重',
  exportReport: '导出报告',
  testValidate: '测试验证',
  pending: '等待中',
  running: '训练中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  excellent: '优秀',
  good: '良好',
  improve: '需改进',
  epoch: '轮次',
  boxLoss: '定位损失',
  clsLoss: '分类损失',
  precision: '精确率',
  recall: '召回率',
  evaluationReport: '评估报告',
  validationSet: '验证集',
  testSet: '测试集',
  perClassAp: '各类别 AP 分析',
  className: '类别',
  evaluation: '评价',
  confusionMatrix: '混淆矩阵',
  prCurve: 'PR 曲线',
  f1Curve: 'F1 曲线',
  dateLocale: 'zh-CN',
  fetchTasksFailed: '训练任务列表加载失败',
  fetchDatasetsFailed: '训练数据集加载失败',
  retry: '重试',
  deleteSuccess: '训练历史任务已删除',
})

const { trainingTasks: taskList, loadingTrainingTasks: loadingTasks } = storeToRefs(taskStore)
const pageError = ref(null)
const monitorError = ref(null)
const selectedTask = ref(null)
const showCreateDialog = ref(false)
const creating = ref(false)
const taskExpanded = ref(true)
const monitorExpanded = ref(true)

const lossChartRef = ref(null)
const mapChartRef = ref(null)
let lossChart = null
let mapChart = null
let pollTimer = null
let monitorSelectionVersion = 0
let metricsRequestInFlight = null
let hasExplicitTaskSelection = false

const confusionChartRef = ref(null)
const prChartRef = ref(null)
const f1ChartRef = ref(null)
let confusionChart = null
let prChart = null
let f1Chart = null

const evalReport = ref(null)
const validating = ref(false)

const showExportDialog = ref(false)
const exporting = ref(false)
const downloading = ref(false)
const exportForm = ref({
  version: '',
  description: '',
  set_default: false,
  upload_minio: true,
})

const showPredictDialog = ref(false)
const predicting = ref(false)
const predictFile = ref(null)
const predictConf = ref(0.25)
const predictIou = ref(0.45)
const predictResult = ref(null)
const predictChartRef = ref(null)
let predictChart = null

const trainForm = ref({
  scene_id: null,
  dataset_path: '',
  model_name: 'yolo11n',
  epochs: 50,
  batch_size: 8,
  img_size: 640,
  device: 'cpu',
  optimizer: 'SGD',
  lr0: 0.01,
})
const scenes = ref([])
const datasets = ref([])
const uploadingDataset = ref(false)
const loadingDatasets = ref(false)

const metricCards = computed(() => {
  const task = selectedTask.value
  if (!task) return []
  const metric = task.latest_metric

  return [
    { label: text.value.epoch, value: `${metric?.epoch ?? task.current_epoch ?? 0}/${task.epochs ?? 0}` },
    { label: text.value.boxLoss, value: formatMetric(metric?.box_loss) },
    { label: text.value.clsLoss, value: formatMetric(metric?.cls_loss) },
    { label: text.value.precision, value: formatPercent(metric?.precision) },
    { label: 'mAP@50', value: formatPercent(metric?.map50) },
    { label: 'mAP@50-95', value: formatPercent(metric?.map50_95) },
  ]
})

const evalMetricCards = computed(() => {
  const overall = evalReport.value?.overall
  if (!overall) return []

  return [
    {
      label: text.value.precision,
      value: formatPercent(overall.precision),
      color: overall.precision > 0.7 ? '#67c23a' : '#e6a23c',
    },
    {
      label: text.value.recall,
      value: formatPercent(overall.recall),
      color: overall.recall > 0.7 ? '#67c23a' : '#e6a23c',
    },
    {
      label: 'mAP@50',
      value: formatPercent(overall.map50),
      color: overall.map50 > 0.5 ? '#67c23a' : '#f56c6c',
    },
    {
      label: 'mAP@50-95',
      value: formatPercent(overall.map50_95),
      color: overall.map50_95 > 0.3 ? '#67c23a' : '#f56c6c',
    },
  ]
})

const perClassData = computed(() => {
  const perClass = evalReport.value?.per_class
  if (!perClass) return []

  return Object.entries(perClass)
    .map(([className, metrics]) => ({
      class_name: className,
      ap50: metrics.ap50,
      ap50_95: metrics.ap50_95,
    }))
    .sort((a, b) => b.ap50 - a.ap50)
})

const annotatedImageSrc = computed(() => {
  const image = predictResult.value?.annotated_image
  if (!image) return ''
  return image.startsWith('data:') ? image : `data:image/jpeg;base64,${image}`
})

function statusText(status) {
  return {
    pending: text.value.pending,
    running: text.value.running,
    completed: text.value.completed,
    failed: text.value.failed,
    cancelled: text.value.cancelled,
  }[status] || status || '-'
}

function progressStatus(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

function normalizeProgress(value) {
  const progress = Number(value)
  if (!Number.isFinite(progress)) return 0
  return Math.min(100, Math.max(0, Math.round(progress)))
}

// Keep the existing component-local translation structure lightweight for
// form labels that are only used once in this workbench.
function bilingual(zh, en) {
  return settingsStore.isEnglish ? en : zh
}

function formatDataset(task) {
  const path = task?.dataset_name || task?.dataset_path
  if (!path) return '-'
  const count = Number(task.dataset_size)
  return Number.isFinite(count) && count > 0 ? `${path} (${count})` : path
}

function isDeletable(task) {
  return task && !RUNNING_STATUSES.has(task.status)
}

function taskIdentifier(task) {
  return task?.id ?? task?.task_id ?? task?.taskId ?? task?.task_uuid ?? task?.taskUuid
}

function formatMetric(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '-'
}

function formatPercent(value) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '-'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(text.value.dateLocale, { hour12: false })
}

function formatBoundingBox(bbox) {
  if (!Array.isArray(bbox)) return '-'
  return `[${bbox.map((value) => Number(value).toFixed(0)).join(', ')}]`
}

function apLevel(ap50) {
  if (ap50 >= 0.7) return { type: 'success', text: text.value.excellent }
  if (ap50 >= 0.5) return { type: 'warning', text: text.value.good }
  return { type: 'danger', text: text.value.improve }
}

function tableRowClassName({ row }) {
  return row.ap50 < 0.5 ? 'weak-row' : ''
}

function normalizeTaskStatusResponse(response) {
  if (!response) return null
  const task = response.task || response
  return {
    ...task,
    latest_metric: response.latest_metric ?? task.latest_metric ?? null,
  }
}

function reportPageError(error, fallback, retry) {
  const { code, message } = getApiErrorInfo(error, fallback)
  pageError.value = { message: `[${code}] ${message}`, retry }
}

function reportMonitorError(error, fallback) {
  const { code, message } = getApiErrorInfo(error, fallback)
  monitorError.value = { message: `[${code}] ${message}` }
}

async function retryPageAction() {
  const retry = pageError.value?.retry
  pageError.value = null
  await retry?.()
}

async function retryMonitorAction() {
  monitorError.value = null
  await fetchMetrics()
}

async function fetchTasks() {
  pageError.value = null
  try {
    const [loadedScenes] = await Promise.all([
      getScenesApi(),
      taskStore.fetchTrainingTasks(),
    ])
    scenes.value = loadedScenes
    if (!trainForm.value.scene_id) trainForm.value.scene_id = Number(scenes.value[0]?.id) || null
    const selected = taskList.value.find((task) => task.id === selectedTask.value?.id)
      || taskStore.selectedTrainingTask
    if (selectedTask.value && selected) selectedTask.value = { ...selectedTask.value, ...selected }
    else if (selectedTask.value && !selected) {
      stopPolling()
      selectedTask.value = null
      taskStore.clearSelectedTrainingTask()
    }
    return selected
  } catch (error) {
    console.error('获取训练任务列表失败', error)
    reportPageError(error, text.value.fetchTasksFailed, fetchTasks)
  }
}

function handleCurrentTaskChange(task) {
  if (task) selectTask(task)
}

async function fetchDatasets() {
  loadingDatasets.value = true
  try {
    const response = await getTrainingDatasets()
    datasets.value = response.items || []
    if (!trainForm.value.dataset_path) {
      trainForm.value.dataset_path = datasets.value.find((item) => item.ready && item.status !== 'archived')?.path ?? ''
    }
  } catch (error) {
    console.error('获取训练数据集失败', error)
    reportPageError(error, text.value.fetchDatasetsFailed, fetchDatasets)
  } finally {
    loadingDatasets.value = false
  }
}

async function deleteDataset(dataset) {
  try {
    await ElMessageBox.confirm(
      bilingual(`确定删除数据集“${dataset.name || dataset.path}”？`, `Delete dataset “${dataset.name || dataset.path}”?`),
      bilingual('删除训练数据集', 'Delete training dataset'),
      { type: 'warning' },
    )
    await deleteTrainingDataset(dataset.path)
    if (trainForm.value.dataset_path === dataset.path) trainForm.value.dataset_path = ''
    await fetchDatasets()
    ElMessage.success(bilingual('数据集已删除', 'Dataset deleted'))
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    reportPageError(error, bilingual('数据集删除失败', 'Failed to delete dataset'), () => deleteDataset(dataset))
  }
}

async function handleDatasetUpload(uploadFile) {
  if (!uploadFile.raw) return
  uploadingDataset.value = true
  pageError.value = null
  try {
    const dataset = await uploadTrainingDataset(uploadFile.raw)
    await fetchDatasets()
    trainForm.value.dataset_path = dataset.path
    ElMessage.success('数据集上传并校验通过')
  } catch (error) {
    console.error('上传训练数据集失败', error)
    reportPageError(error, '训练数据集上传失败', () => handleDatasetUpload(uploadFile))
  } finally {
    uploadingDataset.value = false
  }
}

async function selectTask(task) {
  stopPolling()
  hasExplicitTaskSelection = true
  monitorExpanded.value = true
  const selectionVersion = ++monitorSelectionVersion
  selectedTask.value = { ...task }
  taskStore.selectTrainingTask(task.id)
  evalReport.value = null
  predictResult.value = null

  await nextTick()
  initCharts()
  await fetchMetrics(selectionVersion)

  if (RUNNING_STATUSES.has(selectedTask.value?.status)) {
    startPolling()
  }
}

function initCharts() {
  lossChart?.dispose()
  mapChart?.dispose()
  lossChart = lossChartRef.value ? echarts.init(lossChartRef.value) : null
  mapChart = mapChartRef.value ? echarts.init(mapChartRef.value) : null
  updateCharts([])
}

async function fetchMetrics(selectionVersion = monitorSelectionVersion) {
  if (!selectedTask.value) return
  const taskId = taskIdentifier(selectedTask.value)
  if (taskId === undefined || taskId === null || taskId === '') return
  if (metricsRequestInFlight === taskId) return
  metricsRequestInFlight = taskId

  try {
    const [metricsResponse, statusResponse] = await Promise.all([
      getTrainingMetrics(taskId),
      getTrainingStatus(taskId),
    ])
    if (selectionVersion !== monitorSelectionVersion || taskIdentifier(selectedTask.value) !== taskId) return
    const metrics = metricsResponse.metrics || []
    const taskStatus = normalizeTaskStatusResponse(statusResponse)

    if (taskStatus) {
      selectedTask.value = { ...selectedTask.value, ...taskStatus }
      taskStore.upsertTrainingTask(taskStatus)
    }

    updateCharts(metrics)

    if (!RUNNING_STATUSES.has(selectedTask.value.status)) {
      stopPolling()
    }
    monitorError.value = null
  } catch (error) {
    console.error('获取训练监控数据失败', error)
    if (error?.response?.status === 404) {
      stopPolling()
      if (taskIdentifier(selectedTask.value) === taskId) {
        selectedTask.value = null
        taskStore.clearSelectedTrainingTask()
      }
      monitorError.value = null
      return
    }
    reportMonitorError(error, '训练监控数据加载失败')
  } finally {
    if (metricsRequestInFlight === taskId) metricsRequestInFlight = null
  }
}

function updateCharts(metrics) {
  const epochs = metrics.map((metric) => metric.epoch)

  lossChart?.setOption({
    title: { text: '训练损失曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['Box Loss', 'Cls Loss', 'DFL Loss'], bottom: 0 },
    grid: { left: 54, right: 24, top: 52, bottom: 56 },
    xAxis: { type: 'category', data: epochs, name: 'Epoch' },
    yAxis: { type: 'value', name: 'Loss', scale: true },
    series: [
      { name: 'Box Loss', type: 'line', smooth: true, data: metrics.map((m) => m.box_loss) },
      { name: 'Cls Loss', type: 'line', smooth: true, data: metrics.map((m) => m.cls_loss) },
      { name: 'DFL Loss', type: 'line', smooth: true, data: metrics.map((m) => m.dfl_loss) },
    ],
  })

  mapChart?.setOption({
    title: { text: '评估指标曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['mAP@50', 'mAP@50-95', 'Precision', 'Recall'], bottom: 0 },
    grid: { left: 54, right: 24, top: 52, bottom: 56 },
    xAxis: { type: 'category', data: epochs, name: 'Epoch' },
    yAxis: { type: 'value', name: '指标值', min: 0, max: 1 },
    series: [
      {
        name: 'mAP@50',
        type: 'line',
        smooth: true,
        data: metrics.map((m) => m.map50),
        lineStyle: { color: '#409eff' },
        itemStyle: { color: '#409eff' },
      },
      {
        name: 'mAP@50-95',
        type: 'line',
        smooth: true,
        data: metrics.map((m) => m.map50_95),
        lineStyle: { color: '#67c23a' },
        itemStyle: { color: '#67c23a' },
      },
      {
        name: 'Precision',
        type: 'line',
        smooth: true,
        data: metrics.map((m) => m.precision),
        lineStyle: { type: 'dashed', color: '#e6a23c' },
        itemStyle: { color: '#e6a23c' },
      },
      {
        name: 'Recall',
        type: 'line',
        smooth: true,
        data: metrics.map((m) => m.recall),
        lineStyle: { type: 'dashed', color: '#f56c6c' },
        itemStyle: { color: '#f56c6c' },
      },
    ],
  })
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(fetchMetrics, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function createTask() {
  if (!trainForm.value.scene_id) {
    ElMessage.warning('请先选择检测场景')
    return
  }
  if (!trainForm.value.dataset_path) {
    ElMessage.warning('请先选择训练数据集')
    return
  }
  creating.value = true
  pageError.value = null
  try {
    const response = await startTraining(trainForm.value)
    ElMessage.success(`训练任务已创建：${response.task_uuid}`)
    showCreateDialog.value = false
    await fetchTasks()
    const task = taskList.value.find((item) => item.id === response.id)
    if (task) await selectTask(task)
  } catch (error) {
    console.error('创建训练任务失败', error)
    reportPageError(error, '训练任务创建失败', createTask)
  } finally {
    creating.value = false
  }
}

async function retryTask(task) {
  creating.value = true
  pageError.value = null
  try {
    const response = await retryTrainingTask(task.id)
    ElMessage.success(`训练任务已重新创建：${response.task_uuid}`)
    await fetchTasks()
    const retriedTask = taskList.value.find((item) => item.id === response.id)
    if (retriedTask) await selectTask(retriedTask)
  } catch (error) {
    reportPageError(error, '训练任务重试失败', () => retryTask(task))
  } finally {
    creating.value = false
  }
}

async function stopTask(taskId) {
  pageError.value = null
  try {
    await ElMessageBox.confirm('确定要停止当前训练任务吗？训练进度将被保留。', '确认停止', {
      type: 'warning',
    })
    await stopTraining(taskId)
    ElMessage.success('训练任务已停止')
    await fetchTasks()
    if (selectedTask.value?.id === taskId) await fetchMetrics()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('停止训练任务失败', error)
      reportPageError(error, '训练任务停止失败', () => stopTask(taskId))
    }
  }
}

async function deleteTask(task) {
  try {
    await ElMessageBox.confirm(
      bilingual(
        `确定删除训练任务 ${task.task_uuid}？`,
        `Delete training task ${task.task_uuid}?`,
      ),
      text.value.delete,
      { type: 'warning' },
    )
    const identifier = taskIdentifier(task)
    await deleteTrainingTask(identifier)
    if (taskIdentifier(selectedTask.value) === identifier) {
      stopPolling()
      selectedTask.value = null
      taskStore.clearSelectedTrainingTask()
      evalReport.value = null
      predictResult.value = null
    }
    await fetchTasks()
    ElMessage.success(text.value.deleteSuccess)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      reportPageError(error, bilingual('删除训练任务失败', 'Failed to delete training task'), () => deleteTask(task))
    }
  }
}

async function validateModel() {
  if (!selectedTask.value) return
  validating.value = true
  pageError.value = null
  try {
    const response = await validateTrainingModel(selectedTask.value.id, {
      split: 'val',
      conf: 0.001,
      iou: 0.6,
    })
    evalReport.value = response
    await nextTick()
    renderEvaluationCharts(response.visualization)
    ElMessage.success(`评估完成：mAP@50 ${formatPercent(response.overall?.map50)}`)
  } catch (error) {
    console.error('模型评估失败', error)
    reportPageError(error, '模型评估失败', validateModel)
  } finally {
    validating.value = false
  }
}

function renderEvaluationCharts(visualization) {
  confusionChart?.dispose()
  prChart?.dispose()
  f1Chart?.dispose()
  if (!visualization) return

  const matrix = visualization.confusion_matrix || {}
  const labels = matrix.labels || []
  const values = (matrix.matrix || []).flatMap((row, y) => row.map((value, x) => [x, y, value]))
  confusionChart = confusionChartRef.value ? echarts.init(confusionChartRef.value) : null
  confusionChart?.setOption({
    title: { text: text.value.confusionMatrix, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { position: 'top' },
    grid: { left: 82, right: 20, top: 50, bottom: 80 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: labels },
    visualMap: { min: 0, max: Math.max(1, ...values.map((item) => item[2])), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
    series: [{ type: 'heatmap', data: values, label: { show: true }, emphasis: { itemStyle: { shadowBlur: 8 } } }],
  })

  const renderLine = (chartRef, title, curve, xName, yName) => {
    const chart = chartRef.value ? echarts.init(chartRef.value) : null
    chart?.setOption({
      title: { text: title, left: 'center', textStyle: { fontSize: 14 } }, tooltip: { trigger: 'axis' },
      grid: { left: 52, right: 24, top: 50, bottom: 46 },
      xAxis: { type: 'value', name: xName, min: 0, max: 1 }, yAxis: { type: 'value', name: yName, min: 0, max: 1 },
      series: [{ type: 'line', smooth: true, showSymbol: false, data: (curve?.x || []).map((x, index) => [x, curve.y?.[index]]) }],
    })
    return chart
  }
  prChart = renderLine(prChartRef, text.value.prCurve, visualization.pr_curve, text.value.recall, text.value.precision)
  f1Chart = renderLine(f1ChartRef, text.value.f1Curve, visualization.f1_curve, 'Confidence', 'F1')
}

async function exportModel() {
  if (!selectedTask.value) return
  exporting.value = true
  pageError.value = null
  try {
    const response = await exportTrainingModel(selectedTask.value.id, {
      ...exportForm.value,
      version: exportForm.value.version || null,
      description: exportForm.value.description || null,
    })
    ElMessage.success(response.message || '模型导出成功')
    showExportDialog.value = false
  } catch (error) {
    console.error('模型导出失败', error)
    reportPageError(error, '模型导出失败', exportModel)
  } finally {
    exporting.value = false
  }
}

async function downloadModel() {
  if (!selectedTask.value) return
  downloading.value = true
  pageError.value = null
  try {
    const blob = await downloadTrainingModel(selectedTask.value.id)
    triggerBlobDownload(blob, `best_${selectedTask.value.task_uuid}.pt`)
    ElMessage.success('模型权重下载已开始')
  } catch (error) {
    console.error('模型权重下载失败', error)
    reportPageError(error, '模型权重下载失败', downloadModel)
  } finally {
    downloading.value = false
  }
}

async function downloadReport() {
  if (!selectedTask.value) return
  reportDownloading.value = true
  try {
    const blob = await downloadTrainingReport(selectedTask.value.id)
    triggerBlobDownload(blob, `training_report_${selectedTask.value.task_uuid}.md`)
  } catch (error) {
    reportPageError(error, text.value.exportReport, downloadReport)
  } finally {
    reportDownloading.value = false
  }
}

function triggerBlobDownload(blob, filename) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

function openPredictDialog() {
  showPredictDialog.value = true
  predictFile.value = null
  predictResult.value = null
}

function handlePredictFileChange(file) {
  const allowedTypes = ['image/jpeg', 'image/png', 'image/bmp', 'image/webp']
  if (!allowedTypes.includes(file.raw?.type)) {
    predictFile.value = null
    ElMessage.warning('请选择 JPG、PNG、BMP 或 WebP 图片')
    return
  }
  predictFile.value = file.raw
  predictResult.value = null
}

async function runPredict() {
  if (!predictFile.value || !selectedTask.value) return
  predicting.value = true
  pageError.value = null
  try {
    const formData = new FormData()
    formData.append('file', predictFile.value)
    formData.append('task_id', String(selectedTask.value.id))
    formData.append('conf', String(predictConf.value))
    formData.append('iou', String(predictIou.value))

    predictResult.value = await predictTrainingImage(formData)
    await nextTick()
    renderPredictChart(predictResult.value.class_counts || {})
    ElMessage.success(`检测完成：发现 ${predictResult.value.total_objects} 个目标`)
  } catch (error) {
    console.error('测试图验证失败', error)
    reportPageError(error, '测试图验证失败', runPredict)
  } finally {
    predicting.value = false
  }
}

function renderPredictChart(classCounts) {
  disposePredictChart()
  if (!predictChartRef.value) return

  predictChart = echarts.init(predictChartRef.value)
  predictChart.setOption({
    title: { text: '类别统计', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'item' },
    legend: { type: 'scroll', bottom: 0 },
    series: [
      {
        name: '目标数量',
        type: 'pie',
        radius: ['35%', '62%'],
        center: ['50%', '45%'],
        data: Object.entries(classCounts).map(([name, value]) => ({ name, value })),
      },
    ],
  })
}

function disposePredictChart() {
  predictChart?.dispose()
  predictChart = null
}

function resizeCharts() {
  lossChart?.resize()
  mapChart?.resize()
  predictChart?.resize()
  confusionChart?.resize()
  prChart?.resize()
  f1Chart?.resize()
}

onMounted(() => {
  fetchTasks().then((restoredTask) => {
    const requestedTask = taskList.value.find((task) => String(task.id) === String(route.query.task || ''))
    if (requestedTask) selectTask(requestedTask)
    else {
      const initialTask = restoredTask || taskList.value[0]
      if (initialTask && !selectedTask.value && !hasExplicitTaskSelection) selectTask(initialTask)
    }
  })
  fetchDatasets()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  stopPolling()
  lossChart?.dispose()
  mapChart?.dispose()
  disposePredictChart()
  confusionChart?.dispose()
  prChart?.dispose()
  f1Chart?.dispose()
  window.removeEventListener('resize', resizeCharts)
})
</script>

<style lang="scss" scoped>
.training-page {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0;
}

.page-alert,
.monitor-alert {
  margin-bottom: 16px;
}

.section-card {
  margin-bottom: 20px;
}

.resource-section { margin-top: 18px; }
.resource-section-hint { color: var(--app-text-secondary); font-size: 12px; }
.monitor-header { align-items: center; }
.monitor-header .monitor-info { flex: 1; }
.monitor-toggle { margin-left: auto; flex-shrink: 0; }

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;

  > div {
    display: flex;
    align-items: center;
    gap: 10px;
  }
}

.card-title {
  color: $text-primary;
  font-weight: 600;
}

.card-caption,
.form-hint {
  color: $text-secondary;
  font-size: 12px;
}

.form-hint {
  margin-left: 8px;
}

.monitor-info {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 16px;
  color: $text-secondary;
  font-size: 13px;
}

.monitor-progress {
  margin-bottom: 18px;
}

.metric-grid {
  row-gap: 16px;
}

.metric-item {
  height: 84px;
  padding: 14px 10px;
  text-align: center;
  background: #f8fafc;
  border: 1px solid #ebeef5;
  border-radius: $border-radius-md;
}

.metric-value {
  color: $text-primary;
  font-size: 21px;
  font-weight: 700;
}

.metric-label {
  margin-top: 6px;
  color: $text-secondary;
  font-size: 12px;
}

.chart-grid {
  margin-top: 18px;
  row-gap: 16px;
}

.chart-panel {
  height: 350px;
  border: 1px solid #ebeef5;
  border-radius: $border-radius-md;
}

.evaluation-metrics {
  margin-bottom: 22px;
}

.subsection-title {
  margin: 0 0 12px;
  color: $text-primary;
  font-weight: 600;
}

.weak-value {
  color: $danger-color;
  font-weight: 600;
}

.plot-notice {
  margin-top: 16px;
}

.full-width {
  width: 100%;
}

.dataset-picker {
  display: flex;
  width: 100%;
  gap: 8px;
}

.upload-icon {
  margin-bottom: 8px;
  color: $text-secondary;
  font-size: 42px;
}

.predict-settings {
  margin-top: 18px;
}

.predict-result {
  min-height: 380px;
}

.annotated-image {
  display: block;
  width: 100%;
  max-height: 360px;
  margin-bottom: 12px;
  object-fit: contain;
  background: #f5f7fa;
  border-radius: $border-radius-md;
}

.predict-chart {
  height: 240px;
  margin: 12px 0;
}

:deep(.weak-row) {
  --el-table-tr-bg-color: #fef0f0;
}

@media (max-width: 768px) {
  .monitor-header,
  .card-header {
    align-items: stretch;
    flex-direction: column;
  }

  .page-header .el-button {
    width: 100%;
  }

  .monitor-info {
    justify-content: flex-start;
  }
}
</style>
