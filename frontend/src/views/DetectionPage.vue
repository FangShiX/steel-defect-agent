<template>
  <div class="frontend-b-page">
    <ModulePageHeader
      :title="text.title"
    >
      <RefreshButton :label="text.resetMode" @click="resetCurrentMode" />
    </ModulePageHeader>

    <PageErrorAlert
      v-if="pageError"
      :message="pageError"
      :retry-text="text.resetMode"
      closable
      @retry="resetCurrentMode"
      @close="pageError = ''"
    />

    <el-tabs v-model="activeMode" class="mode-tabs">
      <el-tab-pane :label="text.singleTab" name="single">
        <div class="detection-layout">
          <section class="control-card">
            <div class="section-title">
              <h3>{{ text.configTitle }}</h3>
              <span v-if="modelWarmupStatus === 'ready'" class="model-status ok">● {{ text.modelReady }}</span>
              <span v-else-if="modelWarmupStatus === 'loading'" class="model-status loading">● {{ text.modelWarming }}</span>
              <span v-else-if="modelWarmupStatus === 'error'" class="model-status err">● {{ text.modelWarmFailed(warmupError) }}</span>
            </div>

            <el-form label-position="top" class="compact-form">
              <div class="form-row">
                <el-form-item :label="text.scene">
                  <el-select v-model="form.sceneId" class="full-width" @change="loadModels" size="small">
                    <el-option v-for="scene in scenes" :key="scene.id" :label="sceneLabel(scene)" :value="scene.id" />
                  </el-select>
                </el-form-item>
                <el-form-item :label="text.modelVersion">
                  <el-select v-model="form.modelId" class="full-width" size="small">
                    <el-option v-for="model in models" :key="model.id" :value="model.id" :label="`${model.modelType} · ${model.version}`">
                      <div class="model-option"><span>{{ model.modelType }} · {{ model.version }}</span><small>mAP50 {{ formatPercent(model.map50) }}</small></div>
                    </el-option>
                  </el-select>
                </el-form-item>
              </div>
              <div class="form-row">
                <el-form-item>
                  <template #label><span>置信度</span></template>
                  <el-input-number v-model="form.confThreshold" :min="0.1" :max="0.9" :step="0.05" size="small" controls-position="right" class="slider-num-full" />
                  <el-slider v-model="form.confThreshold" :min="0.1" :max="0.9" :step="0.05" size="small" />
                </el-form-item>
                <el-form-item>
                  <template #label><span>IoU</span></template>
                  <el-input-number v-model="form.iouThreshold" :min="0.1" :max="0.9" :step="0.05" size="small" controls-position="right" class="slider-num-full" />
                  <el-slider v-model="form.iouThreshold" :min="0.1" :max="0.9" :step="0.05" size="small" />
                </el-form-item>
              </div>
            </el-form>

            <div class="detect-upload-card">
              <div
                class="detect-upload-drop"
                role="button"
                tabindex="0"
                @click="triggerSingleFile"
                @keydown.enter.prevent="triggerSingleFile"
                @keydown.space.prevent="triggerSingleFile"
                @dragover.prevent
                @drop.prevent="onSingleFileDrop"
              >
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="detect-upload-cloud">
                  <path d="M7 10V9C7 6.23858 9.23858 4 12 4C14.7614 4 17 6.23858 17 9V10C19.2091 10 21 11.7909 21 14C21 15.4806 20.1956 16.8084 19 17.5M7 10C4.79086 10 3 11.7909 3 14C3 15.4806 3.8044 16.8084 5 17.5M7 10C7.43285 10 7.84965 10.0688 8.24006 10.1959M12 12V21M12 12L15 15M12 12L9 15" stroke="#1a1a1a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <p>{{ singleFile ? singleFile.name : text.dragSingle }}</p>
              </div>
              <label class="detect-upload-footer">
                <p>{{ singleFile ? singleFile.name : text.notSelected }}</p>
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" @click.stop="clearSingleFile"><path d="M5.16565 10.1534C5.07629 8.99181 5.99473 8 7.15975 8H16.8402C18.0053 8 18.9237 8.9918 18.8344 10.1534L18.142 19.1534C18.0619 20.1954 17.193 21 16.1479 21H7.85206C6.80699 21 5.93811 20.1954 5.85795 19.1534L5.16565 10.1534Z" stroke="#1a1a1a" stroke-width="2"/><path d="M19.5 5H4.5" stroke="#1a1a1a" stroke-width="2" stroke-linecap="round"/><path d="M10 3C10 2.44772 10.4477 2 11 2H13C13.5523 2 14 2.44772 14 3V5H10V3Z" stroke="#1a1a1a" stroke-width="2"/></svg>
              </label>
              <button
                class="detect-upload-detect"
                :disabled="!singleFile || !form.modelId"
                @click="startSingleDetection"
              >
                <svg v-if="singleLoading" class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                <span>{{ singleLoading ? text.detecting : text.startDetect }}</span>
              </button>
              <input id="singleFileInput" type="file" :accept="imageAccept" @change="onSingleFileSelected" hidden />
            </div>
          </section>

          <div class="result-square">
            <DetectionResultPanel
            :preview-url="singlePreviewUrl"
            :result="singleResult"
            :loading="singleLoading"
          />
        </div>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="text.batchTab" name="batch">
        <div class="workspace-card">
          <div class="section-title section-title--inline">
            <div>
              <h3>{{ text.batchTitle }}</h3>
              <el-tooltip :content="text.batchHint" placement="top">
                <span class="batch-hint" tabindex="0" aria-label="批量检测限制">?</span>
              </el-tooltip>
            </div>
            <el-button
              type="primary"
              :icon="Files"
              :loading="batchLoading"
              :disabled="batchFileList.length === 0"
              @click="startBatchDetection"
            >{{ text.startBatch }}</el-button>
          </div>
          <el-upload
            ref="batchUploadRef"
            v-model:file-list="batchFileList"
            drag
            multiple
            :auto-upload="false"
            :limit="MAX_BATCH_IMAGES"
            :accept="imageAccept"
            :on-change="validateBatchFile"
            :on-exceed="handleBatchExceed"
          >
            <el-icon class="steel-uploader__icon"><FolderAdd /></el-icon>
            <template v-if="batchFileList.length === 0">
              <div class="el-upload__text">{{ text.dragBatch }} <em>{{ text.clickSelect }}</em></div>
            </template>
            <template v-else>
              <div class="el-upload__text">{{ text.dragMore }}</div>
              <div class="batch-upload-actions">
                <el-button type="primary" plain @click.stop="openBatchFilePicker()">{{ text.addImages }}</el-button>
                <el-button @click.stop="openBatchFilePicker(true)">{{ text.reselect }}</el-button>
              </div>
            </template>
          </el-upload>
          <el-divider content-position="left">{{ text.orZip }}</el-divider>
          <div class="zip-upload-row">
            <el-upload
              v-model:file-list="zipFileList"
              :auto-upload="false"
              :limit="1"
              accept=".zip,application/zip"
              :on-change="validateZipFile"
            >
              <el-button :icon="FolderAdd">{{ text.selectZip }}</el-button>
            </el-upload>
            <span>{{ text.zipHint }}</span>
            <el-button
              type="primary"
              :loading="zipLoading"
              :disabled="zipFileList.length === 0 || !form.modelId"
              @click="startZipDetection"
            >{{ text.detectZip }}</el-button>
          </div>
          <div v-if="batchResult" class="batch-summary">
            <el-tag type="info">{{ batchResult.source === "zip" ? "ZIP" : "多图" }}</el-tag>
            <span v-if="batchResult.source === 'zip'">{{ batchResult.zipFilename }} · {{ batchResult.totalImagesInZip }} 张</span>
            <el-tag type="success">成功 {{ batchResult.successCount }}</el-tag>
            <el-tag type="danger">失败 {{ batchResult.failedCount }}</el-tag>
            <span>任务 {{ batchResult.publicTaskId || batchResult.taskId }}</span>
          </div>
          <el-table v-if="batchResult" :data="batchResult.items" stripe row-key="fileName">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div v-if="row.status === 'completed'" class="batch-detail">
                  <div class="batch-image-card">
                    <span>原图</span>
                    <el-image :src="row.originalImageUrl" :preview-src-list="[row.originalImageUrl]" fit="contain" preview-teleported />
                  </div>
                  <div class="batch-image-card batch-image-card--annotated">
                    <span>检测框结果</span>
                    <el-image :src="row.annotatedImageUrl" :preview-src-list="[row.annotatedImageUrl]" fit="contain" preview-teleported />
                  </div>
                  <el-table :data="row.objects" size="small" class="batch-object-table">
                    <el-table-column prop="classNameCn" label="缺陷类别" min-width="100" />
                    <el-table-column label="置信度" width="90">
                      <template #default="scope">{{ (scope.row.confidence * 100).toFixed(1) }}%</template>
                    </el-table-column>
                    <el-table-column label="bbox" min-width="180">
                      <template #default="scope">[{{ scope.row.bbox.map((value) => Math.round(value)).join(", ") }}]</template>
                    </el-table-column>
                  </el-table>
                </div>
                <el-alert v-else :title="row.error || '该图片检测失败'" type="error" :closable="false" />
              </template>
            </el-table-column>
            <el-table-column label="检测框预览" width="150">
              <template #default="{ row }">
                <el-image v-if="row.annotatedImageUrl" class="batch-thumb" :src="row.annotatedImageUrl" :preview-src-list="[row.annotatedImageUrl]" fit="cover" preview-teleported />
                <span v-else>无</span>
              </template>
            </el-table-column>
            <el-table-column prop="fileName" label="文件" min-width="220" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <StatusTag :status="row.status" :label="row.status === 'completed' ? '完成' : '失败'" size="small">
                  {{ row.status === "completed" ? "完成" : "失败" }}
                </StatusTag>
              </template>
            </el-table-column>
            <el-table-column prop="totalObjects" label="缺陷数" width="100" />
            <el-table-column label="推理耗时" width="120">
              <template #default="{ row }">{{ row.inferenceTimeMs }} ms</template>
            </el-table-column>
            <el-table-column label="主要缺陷" min-width="180">
              <template #default="{ row }">
                {{ [...new Set(row.objects.map((item) => item.classNameCn))].join("、") }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="text.videoTab" name="video">
        <div class="two-column-cards">
          <section class="workspace-card">
            <div class="section-title">
              <div><h3>{{ text.videoTaskTitle }}</h3></div>
            </div>
            <el-upload
              v-model:file-list="videoFileList"
              drag
              :auto-upload="false"
              :limit="1"
              accept=".mp4,.avi,.mov,.mkv,.wmv,.flv"
              :on-change="validateVideoFile"
            >
              <el-icon class="steel-uploader__icon"><VideoCamera /></el-icon>
              <div class="el-upload__text">{{ text.selectVideo }}</div>
            </el-upload>
            <el-form label-position="top" class="video-options">
              <el-form-item :label="text.frameInterval">
                <el-input-number v-model="videoFrameInterval" :min="1" :max="30" />
                <span class="field-suffix">{{ text.frames }}</span>
              </el-form-item>
              <el-form-item :label="text.maxKeyFrames">
                <el-input-number v-model="videoMaxFrames" :min="1" :max="MAX_VIDEO_FRAMES" />
                <span class="field-suffix">{{ text.frames }}</span>
              </el-form-item>
            </el-form>
            <el-button
              type="primary"
              :loading="videoStatus === 'processing'"
              :disabled="videoFileList.length === 0 || videoStatus === 'processing' || !form.modelId"
              @click="startVideoTask"
            >{{ text.createVideoTask }}</el-button>
          </section>
          <section class="workspace-card video-progress-card">
            <el-result
              v-if="videoStatus === 'idle'"
              icon="warning"
              :title="text.noVideoTask"
              :sub-title="text.noVideoTaskHint"
            />
            <template v-else>
              <div class="video-progress-card__header">
                <div><span>{{ text.videoTask }}</span><strong>{{ videoTaskId }}</strong></div>
                <el-tag :type="videoStatus === 'completed' ? 'success' : videoStatus === 'failed' ? 'danger' : 'warning'">
                  {{ videoStatusText(videoStatus) }}
                </el-tag>
              </div>
              <el-progress type="dashboard" :percentage="videoProgress" :status="videoStatus === 'completed' ? 'success' : videoStatus === 'failed' ? 'exception' : ''" />
              <p>{{ videoMessage }}</p>
              <template v-if="videoResult">
                <div class="video-summary">
                  <el-tag type="primary">{{ text.localModel }} {{ videoResult.model?.name || text.unknown }}</el-tag>
                  <el-tag>{{ text.duration }} {{ videoResult.duration_seconds }}s</el-tag>
                  <el-tag>FPS {{ videoResult.fps }}</el-tag>
                  <el-tag>{{ text.resolution }} {{ videoResult.video_resolution.width }}×{{ videoResult.video_resolution.height }}</el-tag>
                  <el-tag type="success">{{ text.objects }} {{ videoResult.total_objects }}</el-tag>
                </div>
                <video v-if="videoResult.annotated_video_url" class="annotated-video" :src="videoResult.annotated_video_url" controls preload="metadata" />
                <div class="class-counts">
                  <el-tag v-for="(count, name) in videoResult.class_counts" :key="name" effect="plain">{{ name }} · {{ count }}</el-tag>
                </div>
                <div v-if="thumbnailFrames.length" class="key-frame-grid">
                  <figure v-for="frame in thumbnailFrames" :key="frame.frame_index">
                    <el-image :src="`data:image/jpeg;base64,${frame.annotated_image_base64}`" :preview-src-list="thumbnailFrameUrls" fit="cover" preview-teleported />
                    <figcaption>
                      <strong>{{ frame.timestamp }}s · {{ text.objectCount(frame.object_count) }}</strong>
                      <span v-for="item in frame.detections" :key="`${frame.frame_index}-${item.class_id}-${item.bbox.join('-')}`">{{ displayDefect(item.class_name_cn) }} {{ (item.confidence * 100).toFixed(1) }}%</span>
                    </figcaption>
                  </figure>
                </div>
                <el-empty v-else :description="text.noKeyFrames" :image-size="72" />
              </template>
            </template>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="text.cameraTab" name="camera">
        <div class="two-column-cards">
          <section class="workspace-card camera-stage">
            <video ref="cameraVideo" autoplay muted playsinline class="camera-source" />
            <canvas ref="cameraCanvas" class="camera-canvas" width="640" height="480" />
            <div v-if="!cameraActive" class="camera-placeholder">
              <el-icon><VideoCamera /></el-icon><span>{{ text.cameraNotStarted }}</span>
            </div>
          </section>
          <section class="workspace-card camera-control">
            <div class="section-title"><div><h3>{{ text.cameraTitle }}</h3></div></div>
            <el-radio-group v-model="cameraMode" :disabled="cameraActive || cameraConnecting" class="camera-mode">
              <el-radio-button value="cpu">{{ text.cpuMode }}</el-radio-button>
              <el-radio-button value="gpu">{{ text.gpuMode }}</el-radio-button>
            </el-radio-group>
            <div class="camera-metrics">
              <div><span>{{ text.status }}</span><strong>{{ cameraStatusText }}</strong></div>
              <div><span>{{ text.localModel }}</span><strong>{{ selectedModelName }}</strong></div>
              <div><span>{{ text.liveFps }}</span><strong>{{ cameraFps }} FPS</strong></div>
              <div><span>{{ text.inferenceTime }}</span><strong>{{ cameraInferenceTime }} ms</strong></div>
              <div><span>{{ text.processedFrames }}</span><strong>{{ cameraFrameCount }}</strong></div>
              <div><span>{{ text.currentObjects }}</span><strong>{{ cameraDetections.length }}</strong></div>
            </div>
            <el-table v-if="cameraDetections.length" :data="cameraDetections" size="small" max-height="180">
              <el-table-column :label="text.defect" min-width="100">
                <template #default="{ row }">{{ displayDefect(row.class_name_cn) }}</template>
              </el-table-column>
              <el-table-column :label="text.confidence" width="90"><template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template></el-table-column>
              <el-table-column label="bbox" min-width="180"><template #default="{ row }">[{{ row.bbox.map((value) => Math.round(value)).join(", ") }}]</template></el-table-column>
            </el-table>
            <el-button v-if="!cameraActive" type="primary" :icon="VideoCamera" :loading="cameraConnecting" :disabled="!form.modelId" @click="startCamera">{{ text.startCamera }}</el-button>
            <el-button v-else type="danger" plain native-type="button" @click.stop.prevent="stopCamera">{{ text.stopCamera }}</el-button>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import {
  Aim,
  Files,
  FolderAdd,
  Setting,
  UploadFilled,
  VideoCamera,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { detectBatchApi, detectSingleApi, detectVideoApi, detectZipApi, getDetectionModelStatus, getVideoStatusApi, MAX_BATCH_IMAGES, MAX_VIDEO_FRAMES, MAX_ZIP_SIZE_BYTES } from "@/api/detection";
import { getModelsApi, getScenesApi } from "@/api/models";
import { createCameraWs } from "@/utils/cameraWs";
import ModulePageHeader from "@/components/common/ModulePageHeader.vue";
import PageErrorAlert from "@/components/common/PageErrorAlert.vue";
import RefreshButton from "@/components/common/RefreshButton.vue";
import StatusTag from "@/components/common/StatusTag.vue";
import DetectionResultPanel from "@/components/detection/DetectionResultPanel.vue";
import { getApiErrorMessage } from "@/utils/apiError";
import { displayDefectName, displaySceneName } from "@/utils/displayText";

const imageAccept = ".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp";
const settingsStore = useSettingsStore()
const route = useRoute()
const activeMode = ref("single");
const pageError = ref("");
const scenes = ref([]);
const models = ref([]);
const form = reactive({ sceneId: "", modelId: "", confThreshold: 0.25, iouThreshold: 0.45 });

const singleFileList = ref([]);
const singleUploadRef = ref();
const singleFile = ref(null);
const singlePreviewUrl = ref("");
const singleResult = ref(null);
const singleLoading = ref(false);
const modelWarmupStatus = ref("loading");
const warmupError = ref("");
let warmupTimer;
let warmupRequesting = false;

const batchFileList = ref([]);
const batchUploadRef = ref();
const batchResult = ref(null);
const batchLoading = ref(false);
const zipFileList = ref([]);
const zipLoading = ref(false);

const videoFileList = ref([]);
const videoFrameInterval = ref(5);
const videoMaxFrames = ref(MAX_VIDEO_FRAMES);
const videoStatus = ref("idle");
const videoProgress = ref(0);
const videoTaskId = ref("");
const videoMessage = ref("");
const videoResult = ref(null);
let videoPollTimer;
const thumbnailFrames = computed(() =>
  (videoResult.value?.key_frames ?? []).filter((frame) => frame.annotated_image_base64).slice(0, 6),
);
const thumbnailFrameUrls = computed(() =>
  thumbnailFrames.value.map((frame) => `data:image/jpeg;base64,${frame.annotated_image_base64}`),
);
const selectedModelName = computed(() => {
  const model = models.value.find((item) => item.id === form.modelId);
  return model ? `${model.modelType} · ${model.version}` : text.value.notSelected;
});

const cameraStatusText = computed(() => {
  if (cameraConnecting.value) return text.value.connecting
  if (cameraActive.value) return text.value.running
  return text.value.notStarted
})

const text = computed(() => settingsStore.isEnglish ? {
  title: 'Detection Workspace',
  resetMode: 'Reset current mode',
  singleTab: 'Single image',
  batchTab: 'Batch',
  videoTab: 'Video',
  cameraTab: 'Camera',
  configTitle: 'Detection Config',
  configHint: 'Supports JPG, PNG, BMP and TIF. Single file up to 10 MB.',
  modelWarming: 'Warming up detection model...',
  modelWarmFailed: (error) => `Model warmup failed${error ? `: ${error}` : ''}. It will load on first detection.`,
  modelDetecting: 'Model loaded, running detection',
  modelReady: 'Detection model is ready',
  scene: 'Detection scene',
  modelVersion: 'Model version',
  confThreshold: 'Confidence threshold',
  iouThreshold: 'IoU threshold',
  dragSingle: 'Drop a steel surface image, or',
  dragBatch: 'Drop multiple steel surface images, or',
  clickSelect: 'click to select',
  uploadTip: 'Only local preview is generated before you start detection.',
  detecting: 'Detecting',
  startDetect: 'Start defect detection',
  batchTitle: 'Batch Image Detection',
  batchHint: `Up to ${MAX_BATCH_IMAGES} images; one failed image will not affect others.`,
  startBatch: 'Start batch detection',
  dragMore: 'Drop images to add more, or choose an action',
  addImages: 'Add images',
  reselect: 'Reselect',
  orZip: 'Or upload a ZIP package',
  selectZip: 'Select ZIP',
  zipHint: `Up to ${MAX_BATCH_IMAGES} images; ZIP must be under 50 MB`,
  detectZip: 'Detect ZIP',
  notSelected: 'Not selected',
  invalidImage: 'Please choose a JPG, PNG, BMP, TIF or WebP image',
  imageTooLarge: 'Single image cannot exceed 10 MB',
  batchLimit: `Batch mode supports up to ${MAX_BATCH_IMAGES} images`,
  optionsFailed: 'Failed to load scenes or models',
  detectSuccess: 'Detection completed',
  singleFailed: 'Single-image detection failed. Check the model service and try again.',
  videoTaskTitle: 'Short Video Task',
  selectVideo: 'Select an MP4 / AVI / MOV / MKV video',
  frameInterval: 'Frame interval',
  maxKeyFrames: 'Max key frames',
  frames: 'frames',
  createVideoTask: 'Create video detection task',
  noVideoTask: 'No video task created',
  noVideoTaskHint: 'Select a video and frame sampling parameters to start detection.',
  videoTask: 'Video task',
  localModel: 'Local model',
  unknown: 'Unknown',
  duration: 'Duration',
  resolution: 'Resolution',
  objects: 'Objects',
  objectCount: (count) => `${count} objects`,
  noKeyFrames: 'No key frames to display',
  cameraNotStarted: 'Camera is not started',
  cameraTitle: 'Browser Camera',
  cpuMode: 'CPU power saving',
  gpuMode: 'GPU acceleration',
  status: 'Status',
  liveFps: 'Live FPS',
  inferenceTime: 'Inference time',
  processedFrames: 'Processed frames',
  currentObjects: 'Current objects',
  defect: 'Defect',
  confidence: 'Confidence',
  connecting: 'Connecting',
  running: 'Running',
  notStarted: 'Not started',
  startCamera: 'Start camera',
  stopCamera: 'Stop camera',
  completed: 'Completed',
  failed: 'Failed',
  processing: 'Processing',
} : {
  title: '检测工作台',
  resetMode: '重置当前模式',
  singleTab: '单图检测',
  batchTab: '批量检测',
  videoTab: '视频检测',
  cameraTab: '摄像头',
  configTitle: '检测配置',
  configHint: '支持 JPG、PNG、BMP、TIF，单文件不超过 10 MB',
  modelWarming: '检测模型预热中，请稍候',
  modelWarmFailed: (error) => `检测模型预热失败${error ? `：${error}` : ''}，首次检测时将自动加载`,
  modelDetecting: '模型加载成功，正在进行检测',
  modelReady: '检测模型加载成功，可以开始检测',
  scene: '检测场景',
  modelVersion: '模型版本',
  confThreshold: '置信度阈值',
  iouThreshold: 'IoU 阈值',
  dragSingle: '拖入钢铁表面图像，或',
  dragBatch: '拖入多张钢铁表面图片，或',
  clickSelect: '点击选择',
  uploadTip: '上传后仅生成本地预览；点击开始检测才会提交。',
  detecting: '正在检测',
  startDetect: '开始缺陷检测',
  batchTitle: '批量图片检测',
  batchHint: `一次最多 ${MAX_BATCH_IMAGES} 张；单张失败不会影响其他图片结果。`,
  startBatch: '开始批量检测',
  dragMore: '拖入图片可新增，或选择操作',
  addImages: '新增图片',
  reselect: '重新选择',
  orZip: '或上传 ZIP 压缩包',
  selectZip: '选择 ZIP',
  zipHint: `最多 ${MAX_BATCH_IMAGES} 张图片，ZIP 不超过 50 MB`,
  detectZip: '检测 ZIP',
  notSelected: '未选择',
  invalidImage: '请选择 JPG、PNG、BMP、TIF 或 WebP 图片',
  imageTooLarge: '单张图片不能超过 10 MB',
  batchLimit: `批量模式一次最多选择 ${MAX_BATCH_IMAGES} 张图片`,
  optionsFailed: '检测场景或模型列表加载失败',
  detectSuccess: '检测完成',
  singleFailed: '单图检测失败，请检查模型服务后重试',
  videoTaskTitle: '短视频任务',
  selectVideo: '选择 MP4 / AVI / MOV / MKV 短视频',
  frameInterval: '抽帧间隔',
  maxKeyFrames: '最多关键帧',
  frames: '帧',
  createVideoTask: '创建视频检测任务',
  noVideoTask: '尚未创建视频任务',
  noVideoTaskHint: '选择视频和抽帧参数后开始检测。',
  videoTask: '视频任务',
  localModel: '本地模型',
  unknown: '未知',
  duration: '时长',
  resolution: '分辨率',
  objects: '目标',
  objectCount: (count) => `${count} 个目标`,
  noKeyFrames: '没有可展示的关键帧',
  cameraNotStarted: '摄像头尚未开启',
  cameraTitle: '浏览器摄像头',
  cpuMode: 'CPU 节能',
  gpuMode: 'GPU 加速',
  status: '状态',
  liveFps: '实时帧率',
  inferenceTime: '推理耗时',
  processedFrames: '已处理帧',
  currentObjects: '当前目标',
  defect: '缺陷',
  confidence: '置信度',
  connecting: '连接中',
  running: '运行中',
  notStarted: '未启动',
  startCamera: '开启摄像头',
  stopCamera: '停止摄像头',
  completed: '已完成',
  failed: '失败',
  processing: '处理中',
})

const cameraVideo = ref();
const cameraCanvas = ref();
const cameraActive = ref(false);
const cameraConnecting = ref(false);
const cameraMode = ref("cpu");
const cameraFps = ref(0);
const cameraFrameCount = ref(0);
const cameraInferenceTime = ref(0);
const cameraDetections = ref([]);
let cameraStream;
let cameraWs;

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function sceneLabel(scene) {
  return displaySceneName(scene.displayName || scene.name, settingsStore.isEnglish);
}

function displayDefect(name) {
  return displayDefectName(name, settingsStore.isEnglish);
}

function videoStatusText(status) {
  if (status === "completed") return text.value.completed;
  if (status === "failed") return text.value.failed;
  return text.value.processing;
}

function validateImage(file) {
  const allowed = ["image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"];
  if (!allowed.includes(file.type)) {
    ElMessage.warning(text.value.invalidImage);
    return false;
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning(text.value.imageTooLarge);
    return false;
  }
  return true;
}

function revokePreview() {
  if (singlePreviewUrl.value) URL.revokeObjectURL(singlePreviewUrl.value);
  singlePreviewUrl.value = "";
}

function triggerSingleFile() {
  document.getElementById('singleFileInput')?.click()
}
function onSingleFileSelected(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!validateImage(file)) { e.target.value = ''; return }
  revokePreview()
  singleFile.value = file
  singlePreviewUrl.value = URL.createObjectURL(file)
  singleResult.value = null
  e.target.value = ''
}
function onSingleFileDrop(e) {
  const file = e.dataTransfer.files?.[0]
  if (!file || !validateImage(file)) return
  revokePreview()
  singleFile.value = file
  singlePreviewUrl.value = URL.createObjectURL(file)
  singleResult.value = null
}
function handleSingleFile(uploadFile) {
  if (!validateImage(uploadFile.raw)) {
    singleFileList.value = [];
    return;
  }
  revokePreview();
  singleFile.value = uploadFile.raw;
  singlePreviewUrl.value = URL.createObjectURL(uploadFile.raw);
  singleResult.value = null;
}

function clearSingleFile() {
  singleFile.value = null;
  singleResult.value = null;
  revokePreview();
}

function handleSingleExceed(files) {
  const nextFile = files[0];
  if (!nextFile || !validateImage(nextFile)) return;

  singleUploadRef.value?.clearFiles();
  singleUploadRef.value?.handleStart(nextFile);
}

function validateBatchFile(uploadFile) {
  if (!validateImage(uploadFile.raw)) {
    batchFileList.value = batchFileList.value.filter((item) => item.uid !== uploadFile.uid);
  }
  if (batchFileList.value.length > MAX_BATCH_IMAGES) {
    ElMessage.warning(text.value.batchLimit);
    batchFileList.value = batchFileList.value.slice(0, MAX_BATCH_IMAGES);
  }
}

function handleBatchExceed() {
  ElMessage.info(text.value.batchLimit);
}

function openBatchFilePicker(replace = false) {
  if (replace) {
    batchUploadRef.value?.clearFiles();
    batchResult.value = null;
  }
  batchUploadRef.value?.$el?.querySelector('input[type="file"]')?.click();
}

async function loadModels() {
  models.value = await getModelsApi(form.sceneId);
  form.modelId = models.value.find((model) => model.isDefault)?.id || models.value[0]?.id || "";
}

async function loadOptions() {
  pageError.value = "";
  try {
    scenes.value = await getScenesApi();
    form.sceneId = scenes.value[0]?.id || "";
    await loadModels();
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.optionsFailed);
  }
}

async function refreshModelWarmupStatus() {
  if (warmupRequesting || ["ready", "error"].includes(modelWarmupStatus.value)) return;
  warmupRequesting = true;
  try {
    const response = await getDetectionModelStatus();
    modelWarmupStatus.value = response.status || "loading";
    warmupError.value = response.error || "";
  } catch (error) {
    modelWarmupStatus.value = "error";
    warmupError.value = getApiErrorMessage(error, "无法获取模型预热状态");
  } finally {
    warmupRequesting = false;
    clearTimeout(warmupTimer);
    if (modelWarmupStatus.value === "loading") {
      warmupTimer = window.setTimeout(refreshModelWarmupStatus, 1500);
    }
  }
}

async function startSingleDetection() {
  if (!singleFile.value) return;
  singleLoading.value = true;
  singleResult.value = null;
  pageError.value = "";
  try {
    singleResult.value = await detectSingleApi(singleFile.value, form);
    ElMessage.success(text.value.detectSuccess);
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.singleFailed);
  } finally {
    singleLoading.value = false;
  }
}

async function startBatchDetection() {
  const files = batchFileList.value.map((item) => item.raw).filter(Boolean);
  if (!files.length) return;
  if (files.length > MAX_BATCH_IMAGES) {
    ElMessage.warning(text.value.batchLimit);
    return;
  }
  batchLoading.value = true;
  batchResult.value = null;
  pageError.value = "";
  try {
    batchResult.value = await detectBatchApi(files, form);
    ElMessage.success(`批量任务完成：${batchResult.value.successCount} 张成功`);
  } catch (error) {
    pageError.value = getApiErrorMessage(error, "批量检测失败");
  } finally {
    batchLoading.value = false;
  }
}

function validateZipFile(uploadFile) {
  const file = uploadFile.raw;
  if (!file?.name.toLowerCase().endsWith(".zip")) {
    ElMessage.warning("请选择 ZIP 压缩包");
    zipFileList.value = [];
    return;
  }
  if (file.size > MAX_ZIP_SIZE_BYTES) {
    ElMessage.warning("ZIP 文件不能超过 50 MB");
    zipFileList.value = [];
  }
}

async function startZipDetection() {
  const file = zipFileList.value[0]?.raw;
  if (!file) return;
  zipLoading.value = true;
  batchResult.value = null;
  pageError.value = "";
  try {
    batchResult.value = await detectZipApi(file, form);
    ElMessage.success(`ZIP 检测完成：${batchResult.value.successCount} 张成功`);
  } catch (error) {
    pageError.value = getApiErrorMessage(error, "ZIP 检测失败");
  } finally {
    zipLoading.value = false;
  }
}

function validateVideoFile(uploadFile) {
  if (uploadFile.raw?.size > MAX_ZIP_SIZE_BYTES) {
    ElMessage.warning("视频文件不能超过 50 MB");
    videoFileList.value = [];
  }
}

async function pollVideoStatus() {
  try {
    const data = await getVideoStatusApi(videoTaskId.value);
    videoStatus.value = data.status;
    videoProgress.value = Math.round(data.progress ?? 0);
    videoMessage.value = data.message ?? "视频处理中...";
    if (data.status === "completed") {
      videoResult.value = data.result ?? null;
      clearInterval(videoPollTimer);
      ElMessage.success("视频检测完成");
    } else if (data.status === "failed") {
      clearInterval(videoPollTimer);
      ElMessage.error(data.message || "视频检测失败");
    }
  } catch (error) {
    clearInterval(videoPollTimer);
    videoStatus.value = "failed";
    videoMessage.value = getApiErrorMessage(error, "视频任务进度查询失败");
    pageError.value = videoMessage.value;
  }
}

async function startVideoTask() {
  const file = videoFileList.value[0]?.raw;
  if (!file) return;
  clearInterval(videoPollTimer);
  videoStatus.value = "processing";
  videoProgress.value = 0;
  videoMessage.value = "正在上传视频...";
  videoResult.value = null;
  pageError.value = "";
  try {
    const data = await detectVideoApi(file, {
      ...form,
      frameSampleRate: videoFrameInterval.value,
      maxFrames: videoMaxFrames.value,
    });
    videoTaskId.value = String(data.task_id);
    videoMessage.value = data.message;
    videoPollTimer = window.setInterval(pollVideoStatus, 1500);
    await pollVideoStatus();
  } catch (error) {
    videoStatus.value = "failed";
    videoMessage.value = getApiErrorMessage(error, "视频上传或任务创建失败");
    pageError.value = videoMessage.value;
  }
}
async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    ElMessage.warning("当前浏览器不支持摄像头访问");
    return;
  }
  try {
    cameraConnecting.value = true;
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false,
    });
    cameraVideo.value.srcObject = cameraStream;
    await cameraVideo.value.play();
    cameraCanvas.value.width = cameraVideo.value.videoWidth || 640;
    cameraCanvas.value.height = cameraVideo.value.videoHeight || 480;
    cameraWs = createCameraWs({
      mode: cameraMode.value,
      conf: form.confThreshold,
      iou: form.iouThreshold,
      modelId: form.modelId,
      onConfigOk: () => {
        cameraConnecting.value = false;
        requestAnimationFrame(sendCameraFrame);
      },
      onResult: handleCameraResult,
      onFrameSkipped: (data) => window.setTimeout(sendCameraFrame, data.retry_after_ms ?? 300),
      onError: (error) => {
        cameraConnecting.value = false;
        const message = typeof error === "string" ? error : `${error?.message || "WebSocket request failed"}${error?.requestId ? ` (Request ID: ${error.requestId})` : ""}`;
        pageError.value = message;
        ElMessage.error(message);
      },
      onReconnect: (attempt, total) => {
        cameraConnecting.value = true;
        pageError.value = `摄像头连接中断，正在重连（${attempt}/${total}）`;
      },
      onReconnectFailed: () => {
        stopCamera();
        pageError.value = "摄像头连接重试失败，已释放设备，请检查后端后重新开始";
        ElMessage.error(pageError.value);
      },
      onClose: () => { cameraConnecting.value = false; },
    });
    cameraWs.connect();
    cameraActive.value = true;
  } catch (error) {
    cameraConnecting.value = false;
    pageError.value =
      error?.name === "NotAllowedError"
        ? "摄像头权限被拒绝，请在浏览器设置中允许访问"
        : "无法访问摄像头，请检查浏览器权限和设备状态";
    ElMessage.error(pageError.value);
  }
}

function sendCameraFrame() {
  if (!cameraActive.value || !cameraWs?.isConnected || cameraVideo.value?.readyState < 2) return;
  const size = cameraMode.value === "cpu" ? 416 : 640;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const width = cameraVideo.value.videoWidth;
  const height = cameraVideo.value.videoHeight;
  const scale = Math.min(size / width, size / height);
  context.fillStyle = "#000";
  context.fillRect(0, 0, size, size);
  context.drawImage(cameraVideo.value, (size - width * scale) / 2, (size - height * scale) / 2, width * scale, height * scale);
  cameraWs.sendFrame(canvas.toDataURL("image/jpeg", 0.6).split(",")[1]);
}

function handleCameraResult(data) {
  cameraFps.value = data.fps ?? 0;
  cameraFrameCount.value = data.frame_count ?? 0;
  cameraInferenceTime.value = data.inference_time ?? 0;
  cameraDetections.value = data.detections ?? [];
  const image = new Image();
  image.onload = () => {
    const context = cameraCanvas.value?.getContext("2d");
    if (!context) return;
    cameraCanvas.value.width = image.width;
    cameraCanvas.value.height = image.height;
    context.drawImage(image, 0, 0);
    requestAnimationFrame(sendCameraFrame);
  };
  image.src = `data:image/jpeg;base64,${data.annotated_frame}`;
}

function stopCamera() {
  cameraWs?.close();
  cameraWs = undefined;
  cameraStream?.getTracks().forEach((track) => track.stop());
  cameraStream = undefined;
  cameraActive.value = false;
  cameraConnecting.value = false;
  cameraFps.value = 0;
  cameraFrameCount.value = 0;
  cameraInferenceTime.value = 0;
  cameraDetections.value = [];
  if (cameraVideo.value) cameraVideo.value.srcObject = null;
  cameraCanvas.value?.getContext("2d")?.clearRect(0, 0, cameraCanvas.value.width, cameraCanvas.value.height);
}

function resetCurrentMode() {
  if (activeMode.value === "single") {
    singleFileList.value = [];
    clearSingleFile();
  } else if (activeMode.value === "batch") {
    batchFileList.value = [];
    zipFileList.value = [];
    batchResult.value = null;
  } else if (activeMode.value === "video") {
    clearInterval(videoPollTimer);
    videoFileList.value = [];
    videoStatus.value = "idle";
    videoProgress.value = 0;
    videoResult.value = null;
    videoMessage.value = "";
  } else {
    stopCamera();
  }
}

onMounted(() => {
  loadOptions();
  refreshModelWarmupStatus();
  if (route.query.videoTask) {
    activeMode.value = 'video';
    videoTaskId.value = String(route.query.videoTask);
    videoStatus.value = 'processing';
    videoPollTimer = window.setInterval(pollVideoStatus, 1500);
    pollVideoStatus();
  }
});
onBeforeUnmount(() => {
  revokePreview();
  clearInterval(videoPollTimer);
  stopCamera();
  clearTimeout(warmupTimer);
});
</script>

<style lang="scss" scoped>
.frontend-b-page { min-height: 100%; max-width: 1200px; margin: 0 auto; padding: 0; }
.page-alert { margin-bottom: 16px; }
.mode-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.mode-tabs :deep(.el-tabs__item) { height: 44px; font-weight: 600; }
.detection-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: stretch; height: 100%; }
.control-card { padding: 18px 20px; border: 1px solid #e7ebf1; border-radius: 12px; background: #fff; box-shadow: none; display: flex; flex-direction: column; }
.workspace-card { padding: 18px 20px; border: 1px solid #e7ebf1; border-radius: 12px; background: #fff; box-shadow: none; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.section-title h3 { margin: 0; color: #1f2937; font-size: 16px; }
.section-title p { margin: 4px 0 0; color: $text-secondary; font-size: 11px; line-height: 1.5; }
.section-title--inline > div:first-child { display: flex; align-items: center; gap: 8px; }
.batch-hint { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border: 1px solid #94a3b8; border-radius: 50%; color: #64748b; font-size: 12px; font-weight: 600; cursor: help; }
.section-title--inline { align-items: center; }
.full-width { width: 100%; }
.model-option { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.model-option small { color: $text-secondary; }
.slider-label { display: flex; width: 100%; justify-content: space-between; }
.slider-label b { color: #2563eb; }
.detect-upload-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px;
  width: 100%;
  flex: 1;
  min-height: 0;
  margin-top: 6px;
}
.detect-upload-drop {
  width: 100%;
  flex: 1;
  min-height: 100px;
  border: 2px dashed #2563eb;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  cursor: pointer;
  padding: 20px 12px;
  gap: 8px;
  transition: border-color 0.2s;

  &:hover { border-color: #1d4ed8; background: #f8faff; }

  p {
    text-align: center;
    color: #1a1a1a;
    font-size: 13px;
    margin: 0;
  }
}
.detect-upload-cloud { height: 70px; }
.compact-form {
  :deep(.el-form-item) { margin-bottom: 8px; }
  :deep(.el-form-item__label) { padding-bottom: 2px; font-size: 12px; }
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.slider-num-full { width: 100%; margin-bottom: 6px; }
.model-status {
  font-size: 11px;
  font-weight: 600;
  &.ok { color: #059669; }
  &.loading { color: #2563eb; }
  &.err { color: #dc2626; }
}
.detect-upload-footer {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(0,110,255,.075);
  border: 0;
  color: #1a1a1a;
  font-size: 12px;
  gap: 8px;

  svg {
    height: 22px;
    flex-shrink: 0;
  }

  p {
    flex: 1;
    text-align: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin: 0;
  }
}
.model-warmup-alert { margin-bottom: 14px; }
.batch-upload-actions { display: flex; justify-content: center; gap: 10px; }
.result-square {
  aspect-ratio: 1;
  overflow: hidden;
  :deep(.result-panel) {
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  :deep(.result-panel__canvas) {
    flex: 1;
    min-height: 0;
  }
  :deep(.image-stage) {
    max-height: none;
    height: 100%;
    background: transparent;
  }
  :deep(.image-stage img) {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
}
.detect-upload-detect {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: #2563eb;
  color: #fff;
  border: 0;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.2s;

  &:hover:not(:disabled) { background: #1d4ed8; }
  &:disabled { opacity: 0.72; background: #93b4f4; cursor: not-allowed; }

  .spin { animation: dash-spin 1s linear infinite; }
}
.workspace-card :deep(.el-upload-dragger) {
  min-height: 160px;
  border: 2px dashed #c8d4e5;
  border-radius: 10px;
  background: #fbfcfe;
  padding: 24px 16px;
}
.workspace-card :deep(.el-upload-dragger:hover) { border-color: #2563eb; background: #f8faff; }
.workspace-card :deep(.steel-uploader__icon) { color: #64748b; font-size: 34px; margin-bottom: 8px; }
.workspace-card :deep(.el-upload__text) { color: #475569; font-size: 13px; }
.workspace-card :deep(.el-button--primary) { min-height: 36px; border-radius: 8px; }
.workspace-card :deep(.el-button) { border-radius: 8px; }
@keyframes dash-spin { to { transform: rotate(360deg); } }
.workspace-card { min-height: 240px; }
.batch-summary { display: flex; align-items: center; gap: 9px; margin: 18px 0 12px; }
.batch-summary span { color: $text-secondary; font-size: 12px; }
.batch-summary > span:last-child { margin-left: auto; }
.zip-upload-row { display: flex; align-items: center; gap: 12px; }
.zip-upload-row > span { flex: 1; color: $text-secondary; font-size: 12px; }
.batch-thumb { width: 118px; height: 74px; border-radius: 7px; background: #101828; }
.batch-detail { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(220px, 1fr); gap: 14px; padding: 12px 18px; }
.batch-image-card { overflow: hidden; border: 1px solid #e7ebf1; border-radius: 10px; background: #f8fafc; }
.batch-image-card > span { display: block; padding: 8px 10px; color: $text-secondary; font-size: 12px; font-weight: 600; }
.batch-image-card :deep(.el-image) { display: block; width: 100%; height: 260px; background: #101828; }
.batch-image-card--annotated { border-color: #bfdbfe; }
.batch-object-table { grid-column: 1 / -1; }
.two-column-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.two-column-cards > .workspace-card { min-height: 320px; }
.video-options { margin-top: 18px; }
.field-suffix { margin-left: 8px; color: $text-secondary; }
.video-progress-card { display: grid; place-items: center; text-align: center; }
.video-progress-card__header { display: flex; width: 100%; align-items: center; justify-content: space-between; text-align: left; }
.video-progress-card__header span, .video-progress-card__header strong { display: block; }
.video-progress-card__header span { color: $text-secondary; font-size: 11px; }
.video-progress-card__header strong { margin-top: 4px; color: #172033; }
.video-progress-card p { color: $text-secondary; font-size: 12px; }
.video-summary, .class-counts { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin: 12px 0; }
.annotated-video { width: 100%; max-height: 300px; border-radius: 10px; background: #101828; }
.key-frame-grid { display: grid; width: 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.key-frame-grid figure { margin: 0; overflow: hidden; border: 1px solid #e7ebf1; border-radius: 8px; background: #f8fafc; }
.key-frame-grid :deep(.el-image) { display: block; width: 100%; aspect-ratio: 16 / 9; background: #101828; }
.key-frame-grid figcaption { display: flex; flex-direction: column; gap: 3px; padding: 7px; color: $text-secondary; font-size: 11px; }
.camera-stage { position: relative; display: grid; min-height: 390px; place-items: center; overflow: hidden; padding: 0; background: #f8fafc; }
.camera-source { position: absolute; width: 1px; height: 1px; opacity: 0; }
.camera-canvas { display: block; width: 100%; min-height: 390px; object-fit: contain; }
.camera-placeholder { display: flex; flex-direction: column; align-items: center; gap: 10px; color: #64748b; }
.camera-placeholder .el-icon { font-size: 52px; }
.camera-control { display: flex; flex-direction: column; align-items: stretch; }
.camera-control :deep(.el-button) { min-height: 36px; border-radius: 8px; }
.camera-mode { margin-bottom: 4px; }
.camera-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 16px 0; }
.camera-metrics div { padding: 12px; border-radius: 9px; background: #f7f9fc; }
.camera-metrics span, .camera-metrics strong { display: block; }
.camera-metrics span { color: $text-secondary; font-size: 11px; }
.camera-metrics strong { margin-top: 4px; color: #172033; font-size: 14px; }
@media (max-width: 1080px) { .detection-layout, .two-column-cards, .batch-detail { grid-template-columns: 1fr; } .batch-object-table { grid-column: 1; } }
@media (max-width: 640px) { .camera-metrics { grid-template-columns: 1fr; } .zip-upload-row { align-items: stretch; flex-direction: column; } }
</style>
