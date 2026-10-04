<template>
  <div
    class="chat-page"
    :class="{ hero: !agentStore.hasMessages }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- ── Empty / Hero state ── -->
    <template v-if="!agentStore.hasMessages">
      <div class="hero-content">
        <h1 class="hero-greeting">{{ greeting }}</h1>

        <!-- Prompt card (hero) -->
        <div class="prompt-area">
          <div :class="['prompt-card', { dragover: isDragover }]">
            <div class="prompt-primary">
              <div v-if="agentStore.selectedImages.length" class="inline-previews">
              <div v-for="(file, i) in agentStore.selectedImages" :key="`${file.name}-${i}`" class="inline-preview">
                  <img v-if="file.type?.startsWith('image/')" :src="agentStore.imagePreviewUrls[i]" alt="preview" />
                  <video v-else-if="file.type?.startsWith('video/')" class="inline-video-preview" :src="agentStore.imagePreviewUrls[i]" controls preload="metadata" />
                  <span v-else class="file-preview-name">{{ file.name }}</span>
                  <button class="remove-preview" @click="agentStore.removeSelectedImage(i)">
                    <el-icon :size="12"><Close /></el-icon>
                  </button>
                </div>
              </div>
              <textarea
                v-model="heroInput"
                class="prompt-textarea"
                :placeholder="chatText.inputPlaceholder"
                rows="1"
                :disabled="agentStore.isStreaming"
                @keydown.enter.exact.prevent="handleHeroSend"
                @input="autoResize"
                ref="heroTextareaRef"
              />
            </div>

            <div class="card-footer">
              <div class="footer-left">
                <ModelSelect v-model="model" />
                <button class="footer-btn" :title="chatText.uploadFile" @click="triggerFileInput">
                  <img :src="addIcon" width="16" height="16" />
                </button>
                <input
                  ref="fileInputRef"
                  type="file"
                  accept="image/png,image/jpeg,image/bmp,image/tiff,image/webp,video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/x-ms-wmv,video/x-flv"
                  multiple
                  hidden
                  @change="onFileChange"
                />
              </div>

              <div class="footer-quick">
                <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('single')">{{ chatText.quickDetect.single }}</button>
                <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('batch')">{{ chatText.quickDetect.batch }}</button>
                <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('zip')">{{ chatText.quickDetect.zip }}</button>
                <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('video')">{{ chatText.quickDetect.video }}</button>
              </div>

              <button
                class="send-btn"
                :disabled="!canSend"
                :title="agentStore.isStreaming ? chatText.stop : chatText.send"
                @click="handleHeroSend"
              >
                <el-icon :size="28">
                  <ArrowUpStroke v-if="!agentStore.isStreaming" size="16" />
                  <CloseBold v-else />
                </el-icon>
              </button>
            </div>
          </div>

          <div v-if="isDragover" class="drag-overlay">
            <el-icon :size="32"><UploadFilled /></el-icon>
            <span>{{ chatText.dropToUpload }}</span>
          </div>
        </div>

        <div class="quick-chips">
          <button
            v-for="chip in quickChips"
            :key="chip.label"
            class="chip"
            @click="handleChipClick(chip.label)"
          >
            <span>{{ chip.label }}</span>
          </button>
        </div>

      </div>
    </template>

    <!-- ── Normal chat state ── -->
    <template v-else>
      <div class="chat-main">
        <MessageList
          :messages="agentStore.messages"
          :is-streaming="agentStore.isStreaming"
          @regenerate="handleRegenerate"
        />
      </div>

      <!-- Prompt card (sticky bottom) -->
      <div class="chat-bottom chat-composer">
        <div :class="['prompt-card', { dragover: isDragover }]">
          <div class="prompt-primary">
            <div v-if="agentStore.selectedImages.length" class="inline-previews">
              <div v-for="(file, i) in agentStore.selectedImages" :key="`${file.name}-${i}`" class="inline-preview">
                <img v-if="file.type?.startsWith('image/')" :src="agentStore.imagePreviewUrls[i]" alt="preview" />
                <video v-else-if="file.type?.startsWith('video/')" class="inline-video-preview" :src="agentStore.imagePreviewUrls[i]" controls preload="metadata" />
                <span v-else class="file-preview-name">{{ file.name }}</span>
                <button class="remove-preview" @click="agentStore.removeSelectedImage(i)">
                  <el-icon :size="12"><Close /></el-icon>
                </button>
              </div>
            </div>
            <textarea
              v-model="chatInput"
              class="prompt-textarea"
              :placeholder="chatText.inputPlaceholder"
              rows="1"
              :disabled="agentStore.isStreaming"
              @keydown.enter.exact.prevent="handleChatSend"
              @input="autoResizeChat"
              ref="chatTextareaRef"
            />
          </div>

          <div class="card-footer">
            <div class="footer-left">
              <ModelSelect v-model="model" />
              <button class="footer-btn" :title="chatText.uploadFile" @click="triggerFileInput">
                <img :src="addIcon" width="16" height="16" />
              </button>
              <input
                ref="fileInputRef"
                type="file"
                accept="image/png,image/jpeg,image/bmp,image/tiff,image/webp,video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/x-ms-wmv,video/x-flv"
                multiple
                hidden
                @change="onFileChange"
              />
            </div>

            <div class="footer-quick">
              <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('single')">{{ chatText.quickDetect.single }}</button>
              <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('batch')">{{ chatText.quickDetect.batch }}</button>
              <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('zip')">{{ chatText.quickDetect.zip }}</button>
              <button class="quick-btn" :disabled="agentStore.isStreaming || isQuickDetecting" @click="handleQuickDetect('video')">{{ chatText.quickDetect.video }}</button>
            </div>

            <button
              class="send-btn"
              :disabled="!canSendChat"
              @click="handleChatSend"
            >
              <el-icon :size="24">
                <ArrowUpStroke :width="16" v-if="!agentStore.isStreaming" />
                <CloseBold v-else />
              </el-icon>
            </button>
          </div>
        </div>

        <div v-if="isDragover" class="drag-overlay">
            <el-icon :size="32"><UploadFilled /></el-icon>
          <span>{{ chatText.dropToUpload }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { CloseBold, Close, UploadFilled } from '@element-plus/icons-vue'
import { ArrowUpStroke } from '@boxicons/vue'
import addIcon from '@/assets/icons/add-circle.svg'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import { useUserStore } from '@/stores/user'
import { DEFAULT_LLM_MODEL_VALUE, useLlmStore } from '@/stores/llm'
import {
  streamAgentChat,
} from '@/api/agent'
import { getHistoryApi } from '@/api/history'
import { detectBatchApi, detectSingleApi, detectVideoApi, detectZipApi, getVideoStatusApi, MAX_BATCH_IMAGES, MAX_VIDEO_FRAMES } from '@/api/detection'
import { getModelsApi, getScenesApi } from '@/api/models'
import { normalizeAgentError, normalizeAgentEvent } from '@/utils/agentCards'
import { reportError } from '@/utils/errorReporter'
import MessageList from '@/components/agent/MessageList.vue'
import ModelSelect from '@/components/agent/ModelSelect.vue'

const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const userStore = useUserStore()

const heroInput = ref('')
const chatInput = ref('')
const heroTextareaRef = ref(null)
const chatTextareaRef = ref(null)
const fileInputRef = ref(null)
const isDragover = ref(false)
const isQuickDetecting = ref(false)
const model = ref(useLlmStore().defaultModel)
let dragCounter = 0

const greeting = computed(() => {
  const hour = new Date().getHours()
  const name = userStore.username
  if (settingsStore.isEnglish) {
    let t = 'Good evening'
    if (hour < 12) t = 'Good morning'
    else if (hour < 18) t = 'Good afternoon'
    return name ? `${t}, ${name}` : t
  }

  let t = '晚上好'
  if (hour < 12) t = '早上好'
  else if (hour < 18) t = '下午好'
  return name ? `${t}，${name}` : t
})

const chatText = computed(() => settingsStore.isEnglish ? {
  inputPlaceholder: 'Enter a detection question...',
  uploadFile: 'Upload file',
  send: 'Send',
  stop: 'Stop',
  dropToUpload: 'Release to upload file',
  onlyImages: 'Unsupported file type',
  imageTooLarge: 'Image size cannot exceed 10MB',
  videoTooLarge: 'Video size cannot exceed 50MB',
  zipDetecting: 'Running ZIP image detection...',
  videoDetecting: 'Uploading and analyzing video...',
  videoQueued: (taskId) => `Video detection task #${taskId} has been recorded. It may take a while; you can check the result in History while it runs.`,
  videoProgress: (progress) => `Video detection in progress (${progress}%)...`,
  videoDone: (frames, count) => `Video detection completed. Analyzed ${frames} key frames and found ${count} possible defects.`,
  zipFailed: 'ZIP detection failed. Please check the archive contents and try again.',
  videoFailed: 'Video detection failed. Please check the video format and backend service.',
  noScene: 'No detection scene is available',
  noModel: 'No detection model is available',
  reconnecting: (count) => `Connection lost. Reconnecting (${count})...`,
  agentUnavailable: 'Agent service is temporarily unavailable',
  agentFailed: 'Agent request failed',
  singleDetecting: 'Running single-image detection...',
  batchDetecting: 'Running batch detection...',
  singleDone: (count) => `Single-image detection completed. Found ${count} possible defects.`,
  batchDone: (images, count) => `Batch detection completed. Processed ${images} images and found ${count} possible defects.`,
  singleFailed: 'Single-image detection failed. Please try again later.',
  batchFailed: 'Batch detection failed. Please try again later.',
  quickDetect: { single: 'Single image', batch: 'Batch images', zip: 'ZIP', video: 'Video' },
  chips: [
    'Analyze defects in this steel surface',
    'What is the detection confidence?',
    'What type of surface defect is this?',
    'How to distinguish scratches and cracks?',
  ],
} : {
  inputPlaceholder: '输入检测问题…',
  uploadFile: '上传文件',
  send: '发送',
  stop: '停止',
  dropToUpload: '释放以上传文件',
  onlyImages: '不支持的文件类型',
  imageTooLarge: '图片大小不能超过 10MB',
  videoTooLarge: '视频大小不能超过 50MB',
  zipDetecting: '正在进行 ZIP 图片检测…',
  videoDetecting: '正在上传并分析视频…',
  videoProgress: (progress) => `视频检测处理中（${progress}%）…`,
  videoDone: (frames, count) => `视频检测完成，共分析 ${frames} 个关键帧，发现 ${count} 个疑似缺陷。`,
  zipFailed: 'ZIP 检测失败，请检查压缩包内容后重试。',
  videoFailed: '视频检测失败，请检查视频格式和后端服务。',
  noScene: '未找到可用检测场景',
  noModel: '未找到可用检测模型',
  reconnecting: (count) => `连接中断，正在第 ${count} 次重连...`,
  agentUnavailable: '智能体服务暂不可用',
  agentFailed: '智能体请求失败',
  singleDetecting: '正在进行单图检测，请稍候……',
  batchDetecting: '正在进行批量检测，请稍候……',
  singleDone: (count) => `单图检测完成，共发现 ${count} 个疑似缺陷。`,
  batchDone: (images, count) => `批量检测完成，共处理 ${images} 张图片，发现 ${count} 个疑似缺陷。`,
  singleFailed: '单图检测失败，请稍后重试。',
  batchFailed: '批量检测失败，请稍后重试。',
  quickDetect: { single: '单图检测', batch: '批量图片检测', zip: 'ZIP 检测', video: '视频检测' },
  chips: [
    '分析这张钢铁表面的缺陷',
    '检测结果置信度是多少',
    '这是什么类型的表面缺陷',
    '如何区分划痕和裂纹',
  ],
})

const canSend = computed(() => {
  return agentStore.isStreaming || heroInput.value.trim() || agentStore.selectedImages.length
})

const canSendChat = computed(() => {
  return agentStore.isStreaming || chatInput.value.trim() || agentStore.selectedImages.length
})

const quickChips = computed(() => chatText.value.chips.map((label) => ({ label })))

const quickDetectOptions = {
  confThreshold: 0.25,
  iouThreshold: 0.45,
}

function onDragEnter() { dragCounter++; isDragover.value = true }
function onDragOver() {}
function onDragLeave() {
  dragCounter--
  if (dragCounter <= 0) { dragCounter = 0; isDragover.value = false }
}
function onDrop(e) {
  dragCounter = 0; isDragover.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleSelectedFile(file)
}

function triggerFileInput() { fileInputRef.value?.click() }

function onFileChange(e) {
  const files = Array.from(e.target?.files || [])
  e.target.value = ''
  files.forEach(handleSelectedFile)
}

function handleSelectedFile(file) {
  const allowed = [
    'image/jpeg', 'image/png', 'image/bmp', 'image/tiff', 'image/webp',
    'video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska',
    'video/x-ms-wmv', 'video/x-flv',
  ]
  if (!allowed.includes(file.type)) { ElMessage.error(chatText.value.onlyImages); return }
  const maxBytes = file.type.startsWith('video/') ? 50 * 1024 * 1024 : 10 * 1024 * 1024
  if (file.size > maxBytes) {
    ElMessage.error(file.type.startsWith('video/') ? '视频大小不能超过 50MB' : chatText.value.imageTooLarge)
    return
  }
  agentStore.addSelectedImages([file])
}

function autoResize() {
  const el = heroTextareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function autoResizeChat() {
  const el = chatTextareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function handleHeroSend() {
  if (agentStore.isStreaming) {
    agentStore.cancelCurrentRun()
    return
  }
  const text = heroInput.value.trim()
  if (!text && !agentStore.selectedImages.length) return
  heroInput.value = ''
  handleSend(text)
}

function handleChatSend() {
  if (agentStore.isStreaming) {
    agentStore.cancelCurrentRun()
    return
  }
  const text = chatInput.value.trim()
  if (!text && !agentStore.selectedImages.length) return
  chatInput.value = ''
  handleSend(text)
}

function handleChipClick(text) {
  heroInput.value = text
  autoResize()
}

function chooseFiles({ accept, multiple }) {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.multiple = multiple
    let settled = false

    const cleanup = () => {
      window.removeEventListener('focus', onFocus)
    }

    const onFocus = () => {
      // { once: true } already removed this listener; just wait for onchange
      // (user picked a file) before treating the refocus as a cancel.
      setTimeout(() => {
        if (!settled) {
          settled = true
          resolve([])
        }
      }, 300)
    }

    input.onchange = () => {
      settled = true
      cleanup()
      resolve(Array.from(input.files || []))
    }

    window.addEventListener('focus', onFocus, { once: true })
    input.click()
  })
}

async function handleQuickDetect(type) {
  if (agentStore.isStreaming || isQuickDetecting.value) return

  isQuickDetecting.value = true
  try {
    const pickerOptions = type === 'zip'
      ? { accept: '.zip,application/zip', multiple: false }
      : type === 'video'
        ? { accept: 'video/mp4,video/avi,video/quicktime,video/x-matroska', multiple: false }
        : { accept: 'image/png,image/jpeg', multiple: type === 'batch' }
    const files = await chooseFiles({
      ...pickerOptions,
    })
    if (!files.length) return

    if (type === 'batch' && files.length > MAX_BATCH_IMAGES) {
      ElMessage.warning(settingsStore.isEnglish ? `Batch detection supports up to ${MAX_BATCH_IMAGES} images.` : `批量检测最多支持 ${MAX_BATCH_IMAGES} 张图片。`)
      return
    }

    const options = await getQuickDetectOptions()
    if (type === 'single') {
      await runSingleDetect(files[0], options)
    } else if (type === 'batch') {
      await runBatchDetect(files, options)
    } else if (type === 'zip') {
      await runZipDetect(files[0], options)
    } else if (type === 'video') {
      await runVideoDetect(files[0], options)
    }
  } finally {
    isQuickDetecting.value = false
  }
}

async function getQuickDetectOptions() {
  const scenes = await getScenesApi()
  const scene = scenes[0]
  if (!scene) throw new Error(chatText.value.noScene)

  const models = await getModelsApi(scene.id)
  const model = models.find((item) => item.isDefault) || models[0]
  if (!model?.id) throw new Error(chatText.value.noModel)

  return { ...quickDetectOptions, modelId: model.id }
}

async function runSingleDetect(file, options) {
  const previewUrl = URL.createObjectURL(file)
  agentStore.addMessage({
    role: 'user',
    content: settingsStore.isEnglish ? `[Quick single detection] ${file.name}` : `[快捷单图检测] ${file.name}`,
    imagePreviewUrls: [previewUrl],
  })
  agentStore.addMessage({
    role: 'assistant',
    content: chatText.value.singleDetecting,
  })
  agentStore.setToolCall({ name: 'detect_single', status: 'running', input: { fileName: file.name } })

  const assistantMessage = agentStore.messages[agentStore.messages.length - 1]
  try {
    const result = await detectSingleApi(file, options)
    assistantMessage.content = chatText.value.singleDone(result.totalObjects || 0)
    assistantMessage.detectionResult = result
    assistantMessage.detectionPreviewUrl = previewUrl
    agentStore.setToolCall({ name: 'detect_single', status: 'success', result })
  } catch (error) {
    assistantMessage.content = chatText.value.singleFailed
    agentStore.setToolCall({ name: 'detect_single', status: 'error', error: error?.message || chatText.value.singleFailed })
    ElMessage.error(error?.response?.data?.detail || chatText.value.singleFailed)
  } finally {
    saveCurrentSession()
  }
}

async function runBatchDetect(files, options) {
  agentStore.addMessage({
    role: 'user',
    content: settingsStore.isEnglish ? `[Quick batch detection] ${files.length} images` : `[快捷批量检测] ${files.length} 张图片`,
  })
  agentStore.addMessage({
    role: 'assistant',
    content: chatText.value.batchDetecting,
  })
  agentStore.setToolCall({ name: 'detect_batch', status: 'running', input: { count: files.length } })

  const assistantMessage = agentStore.messages[agentStore.messages.length - 1]
  try {
    const result = await detectBatchApi(files, options)
    const totalObjects = (result.items || []).reduce((sum, item) => sum + Number(item.totalObjects || 0), 0)
    assistantMessage.content = chatText.value.batchDone(result.items?.length || files.length, totalObjects)
    assistantMessage.detectionResult = result
    agentStore.setToolCall({ name: 'detect_batch', status: 'success', result })
  } catch (error) {
    assistantMessage.content = chatText.value.batchFailed
    agentStore.setToolCall({ name: 'detect_batch', status: 'error', error: error?.message || chatText.value.batchFailed })
    ElMessage.error(error?.response?.data?.detail || chatText.value.batchFailed)
  } finally {
    saveCurrentSession()
  }
}

async function runZipDetect(file, options) {
  agentStore.addMessage({
    role: 'user',
    content: settingsStore.isEnglish ? `[Quick ZIP detection] ${file.name}` : `[快捷 ZIP 检测] ${file.name}`,
  })
  agentStore.addMessage({ role: 'assistant', content: chatText.value.zipDetecting, toolCalls: [] })
  agentStore.setToolCall({ name: 'detect_zip', status: 'running', input: { fileName: file.name } })

  const assistantMessage = agentStore.messages[agentStore.messages.length - 1]
  try {
    const result = await detectZipApi(file, options)
    const totalObjects = (result.items || []).reduce((sum, item) => sum + Number(item.totalObjects || 0), 0)
    assistantMessage.content = chatText.value.batchDone(result.successCount || result.items?.length || 0, totalObjects)
    assistantMessage.detectionResult = result
    agentStore.setToolCall({ name: 'detect_zip', status: 'success', result })
  } catch (error) {
    assistantMessage.content = chatText.value.zipFailed
    agentStore.setToolCall({ name: 'detect_zip', status: 'error', error: error?.message || chatText.value.zipFailed })
    ElMessage.error(error?.response?.data?.detail || chatText.value.zipFailed)
  } finally {
    saveCurrentSession()
  }
}

async function runVideoDetect(file, options) {
  agentStore.addMessage({
    role: 'user',
    content: settingsStore.isEnglish ? `[Quick video detection] ${file.name}` : `[快捷视频检测] ${file.name}`,
  })
  agentStore.addMessage({ role: 'assistant', content: chatText.value.videoDetecting, toolCalls: [] })
  agentStore.setToolCall({ name: 'detect_video', status: 'running', input: { fileName: file.name, progress: 0 } })

  const assistantMessage = agentStore.messages[agentStore.messages.length - 1]
  try {
    const task = await detectVideoApi(file, {
      ...options,
      frameSampleRate: 5,
      maxFrames: MAX_VIDEO_FRAMES,
    })
    assistantMessage.content = settingsStore.isEnglish
      ? chatText.value.videoQueued(task.task_id)
      : `视频检测任务 #${task.task_id} 已入库。处理时间可能较长，可在历史记录中查看进度，完成后将在本对话中显示结果。`
    agentStore.saveSession()

    let status
    for (let attempt = 0; attempt < 240; attempt += 1) {
      status = await getVideoStatusApi(task.task_id)
      const progress = Math.round(status.progress || 0)
      assistantMessage.content = chatText.value.videoProgress(progress)
      agentStore.setToolCall({
        name: 'detect_video',
        status: 'running',
        input: { fileName: file.name, progress },
      })
      if (status.status === 'completed' || status.status === 'failed') break
      await new Promise(resolve => setTimeout(resolve, 1500))
    }

    if (!status || status.status !== 'completed') {
      throw new Error(status?.message || chatText.value.videoFailed)
    }

    const result = status.result || status
    assistantMessage.content = chatText.value.videoDone(result.processed_frames || 0, result.total_objects || 0)
    assistantMessage.videoResult = {
      processedFrames: result.processed_frames || 0,
      totalObjects: result.total_objects || 0,
      classCounts: result.class_counts || {},
      durationSeconds: result.duration_seconds || 0,
      annotatedVideoUrl: result.annotated_video_url || '',
    }
    agentStore.setToolCall({ name: 'detect_video', status: 'success', result })
    agentStore.addToolResultCard(assistantMessage.videoResult, 'detect_video', {
      type: 'video_result',
      task_id: task.task_id,
      model_id: options.modelId,
    })
  } catch (error) {
    assistantMessage.content = chatText.value.videoFailed
    agentStore.setToolCall({ name: 'detect_video', status: 'error', error: error?.message || chatText.value.videoFailed })
    ElMessage.error(error?.response?.data?.detail || error?.message || chatText.value.videoFailed)
  } finally {
    saveCurrentSession()
  }
}

let _currentAgentLabel = ''

function handleAgentEvent(event) {
  const normalized = normalizeAgentEvent(event)
  if (normalized.type === 'agent_switch') {
    _currentAgentLabel = normalized.label || ''
    return
  }
  if (normalized.type === 'run_start') {
    agentStore.activeRunId = normalized.run_id || normalized.runId || normalized.id || agentStore.activeRunId
  }
  if (normalized.type === 'text_delta' || normalized.type === 'text_chunk') {
    const content = normalized.content || ''
    agentStore.appendAssistantContent(content)
  }
  if (normalized.type === 'tool_start') {
    agentStore.setToolCall({
      id: normalized.tool_call_id || normalized.tool_name,
      name: normalized.tool_name,
      status: 'running',
      input: normalized.input,
      agent: normalized.agent || '',
      agentLabel: _currentAgentLabel || normalized.agent || '',
      task_id: normalized.task_id,
      model_id: normalized.model_id,
      file_id: normalized.file_id,
      knowledge_document_id: normalized.knowledge_document_id,
    })
  }
  if (normalized.type === 'tool_delta') {
    agentStore.setToolCall({
      id: normalized.tool_call_id || normalized.tool_name,
      name: normalized.tool_name,
      status: 'running',
      progress: normalized.progress,
      input: normalized.input,
      agentLabel: _currentAgentLabel || normalized.agent || '',
    })
  }
  if (normalized.type === 'tool_result') {
    agentStore.setToolCall({
      id: normalized.tool_call_id || normalized.tool_name,
      name: normalized.tool_name,
      status: 'success',
      result: normalized.result,
      agentLabel: _currentAgentLabel || normalized.agent || '',
      task_id: normalized.task_id,
      model_id: normalized.model_id,
      file_id: normalized.file_id,
      knowledge_document_id: normalized.knowledge_document_id,
    })
    agentStore.addToolResultCard(normalized.result, normalized.tool_name, {
      id: normalized.tool_call_id,
      task_id: normalized.task_id,
      model_id: normalized.model_id,
      file_id: normalized.file_id,
      knowledge_document_id: normalized.knowledge_document_id,
      references: normalized.references,
      snapshot: normalized.snapshot,
    })
  }
  if (normalized.type === 'message_end') {
    agentStore.isStreaming = false
    agentStore.setConnectionStatus('idle')
    agentStore.activeRunId = ''
    const lastMsg = agentStore.messages[agentStore.messages.length - 1]
    if (lastMsg?.role === 'assistant') {
      lastMsg.status = 'done'
      lastMsg.trace = {
        requestId: event.request_id || '',
        sessionId: event.session_id || agentStore.currentSessionId,
        taskIds: event.task_ids || [],
      }
    }
    saveCurrentSession()
    _currentAgentLabel = ''
  }
  if (normalized.type === 'cancelled') {
    agentStore.stopStreaming()
    agentStore.activeRunId = ''
    _currentAgentLabel = ''
  }
  if (normalized.type === 'error') {
    const mapped = normalizeAgentError(normalized.error || normalized, chatText.value.agentFailed)
    agentStore.errorMessage = mapped.code ? `[${mapped.code}] ${mapped.message}` : mapped.message
    reportError(new Error(mapped.message), {
      type: 'sse_error',
      request_id: mapped.requestId,
      task_id: normalized.task_id || normalized.task_ids?.[0],
      session_id: normalized.session_id || agentStore.currentSessionId,
      user_id: normalized.user_id || userStore.user?.id,
      error_code: mapped.code || normalized.error_code,
      retryable: Boolean(mapped.retryable || normalized.retryable),
    })
    agentStore.isStreaming = false
    agentStore.setConnectionStatus('error')
    agentStore.activeRunId = ''
    agentStore.markLastAssistantError(agentStore.errorMessage)
    ElMessage.error(agentStore.errorMessage)
    _currentAgentLabel = ''
  }
}

function doSend(text) {
  agentStore.addMessage({ role: 'assistant', content: '', status: 'streaming', toolCalls: [] })
  agentStore.isStreaming = true
  agentStore.setConnectionStatus('connecting')
  agentStore.currentToolCall = null
  agentStore.errorMessage = ''
  agentStore.activeRunId = ''

  const formData = new FormData()
  formData.append('message', text)
  formData.append('session_id', agentStore.currentSessionId)
  if (model.value && model.value !== DEFAULT_LLM_MODEL_VALUE) {
    formData.append('model', model.value)
  }
  agentStore.selectedImages.forEach(file => formData.append('attachment', file))
  agentStore.clearImages()

  agentStore.abortController = streamAgentChat(formData, {
    onMessage: handleAgentEvent,
    onRetry: ({ retryCount }) => {
      agentStore.reconnectCount = retryCount
      agentStore.setConnectionStatus('reconnecting')
      ElMessage.warning(chatText.value.reconnecting(retryCount))
    },
    onDone: () => {
      agentStore.isStreaming = false
      agentStore.setConnectionStatus('idle')
      agentStore.abortController = null
      agentStore.activeRunId = ''
      agentStore.clearImages()
      saveCurrentSession()
    },
    onError: (error) => {
      agentStore.isStreaming = false
      agentStore.setConnectionStatus('error')
      agentStore.abortController = null
      agentStore.activeRunId = ''
      const mapped = normalizeAgentError(error, chatText.value.agentUnavailable)
      const detail = mapped.code ? `[${mapped.code}] ${mapped.message}${mapped.requestId ? ` (Request ID: ${mapped.requestId})` : ''}` : mapped.message
      reportError(error, {
        type: 'sse_transport_error',
        request_id: error?.requestId,
        task_id: error?.taskId,
        session_id: error?.sessionId || agentStore.currentSessionId,
        user_id: error?.userId || userStore.user?.id,
        error_code: error?.errorCode || error?.code,
        retryable: Boolean(error?.retryable),
      })
      agentStore.markLastAssistantError(detail)
      ElMessage.error(detail)
    },
  })
}

function handleSend(text) {
  if (!text.trim() && !agentStore.selectedImages.length) return
  const imgUrls = agentStore.selectedImages.map(file => URL.createObjectURL(file))
  agentStore.addMessage({ role: 'user', content: text, imagePreviewUrls: imgUrls })
  doSend(text)
}

async function checkAgentToolContracts() {
  if (!localStorage.getItem('ssdd_token')) return

  try {
    await getHistoryApi({ page: 1, pageSize: 1 })
  } catch {
    // Contract probes are best-effort and must not block chat.
  }
}

function handleRegenerate(message) {
  const idx = agentStore.messages.findIndex(m => m.id === message.id)
  if (idx <= 0) return
  const userMsg = agentStore.messages[idx - 1]
  if (userMsg?.role !== 'user') return
  agentStore.messages.splice(idx - 1, 2)
  agentStore.addMessage({ role: 'user', content: userMsg.content || '', imagePreviewUrls: userMsg.imagePreviewUrls || [], attachments: userMsg.attachments || [] })
  doSend(userMsg.content || '')
}

// ── Session history ──
function saveCurrentSession() {
  if (!agentStore.hasMessages) return
  agentStore.saveSession()
}

checkAgentToolContracts()
</script>

<style lang="scss" scoped>
.chat-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;

  &.hero {
    justify-content: center;
  }

  &:not(.hero) {
    overflow: hidden;
  }
}

.chat-main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 100px;
}

/* ── Hero ── */
.hero-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  gap: 28px;
}

.hero-greeting {
  font-size: 34px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.5px;
  margin: 0;
  text-align: center;
}

/* ── Prompt area wrapper ── */
.prompt-area {
  width: 100%;
  max-width: 640px;
  position: relative;
}

/* ── Unified prompt card ── */
.prompt-card {
  display: grid;
  grid-template-rows: 1fr auto;
  grid-template-areas:
    "primary"
    "bottom";
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  position: relative;
  z-index: 1;
  border: 0;
  border-radius: 28px;
  padding: 9px 8px;
  min-height: 102px;
  box-shadow:
    0 0 0 1px rgba(0,0,0,0.04),
    0 2px 8px rgba(0,0,0,0.04),
    0 4px 80px 8px rgba(0,0,0,0.024);
  transition: box-shadow 0.2s;

  &:focus-within {
    box-shadow:
      0 0 0 1px rgba(0,0,0,0.08),
      0 2px 12px rgba(0,0,0,0.06),
      0 4px 80px 8px rgba(0,0,0,0.032);
  }

  &.dragover {
    box-shadow:
      0 0 0 1px #8F8AB0,
      0 2px 8px rgba(143,138,176,0.12);
    background: var(--app-subtle);
  }
}

/* ── Primary area (previews + textarea) ── */
.prompt-primary {
  grid-area: primary;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 9px 10px 0;
}

.prompt-textarea {
  width: 100%;
  border: 0;
  outline: 0;
  resize: none;
  font-size: 16px;
  line-height: 26px;
  color: var(--app-text);
  background: transparent;
  padding: 0 0 16px;
  font-family: inherit;
  min-height: 52px;
  max-height: 160px;
  flex: 1;

  &::placeholder { color: #a3a3a3; }
  &:disabled { opacity: 0.5; }
}

/* ── Inline image previews (inside primary area) ── */
.inline-previews {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 8px;
}

.inline-preview {
  position: relative;

  .file-preview-name {
    display: inline-flex;
    align-items: center;
    width: 120px;
    height: 48px;
    padding: 0 8px;
    border: 1px solid var(--app-border);
    border-radius: 8px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 12px;
  }

  img {
    width: 48px; height: 48px;
    border-radius: 8px;
    object-fit: cover;
    border: 1px solid var(--app-border);
  }

  .inline-video-preview {
    display: block;
    width: 180px;
    max-height: 110px;
    border-radius: 8px;
    background: #111827;
  }

  .remove-preview {
    position: absolute;
    top: -6px; right: -6px;
    width: 20px; height: 20px;
    border-radius: 50%;
    border: 0;
    background: #525252;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: 0;

    &:hover { background: #171717; }
  }
}

/* ── Card footer ── */
.card-footer {
  grid-area: bottom;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  height: 36px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.footer-quick {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: auto;
}

.quick-btn {
  padding: 3px 10px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: transparent;
  color: var(--app-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;

  &:hover:not(:disabled) {
    border-color: #8f8ab0;
    color: var(--app-text);
    background: var(--app-hover);
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
}

/* ── Buttons ── */
.footer-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--app-text);
  cursor: pointer;
  transition: all 0.15s;

  &:hover { background: var(--app-hover); color: var(--app-text); }
}

.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  border: 0;
  border-radius: 50%;
  background: #000000;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover:not(:disabled) { background: #262626; }
  &:disabled { opacity: 0.3; cursor: not-allowed; }
}

:global(:root[data-theme='dark']) .send-btn {
  background: #3f3f46;
  color: #f4f4f5;

  &:hover:not(:disabled) {
    background: #52525b;
  }
}

/* ── Drag overlay ── */
.drag-overlay {
  position: absolute;
  inset: 0;
  border-radius: 16px;
  background: color-mix(in srgb, var(--app-surface) 92%, transparent);
  border: 2px dashed #8F8AB0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #8F8AB0;
  font-size: 14px;
  font-weight: 500;
  z-index: 10;
  pointer-events: none;
}

/* ── Quick chips ── */
.quick-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  max-width: 640px;
}

.chat-quick-detect {
  max-width: 790px;
  margin: 0 auto 8px;
  justify-content: flex-start;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border: 1px solid var(--app-border);
  border-radius: 20px;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;

  &:hover {
    border-color: #8F8AB0;
    color: #8F8AB0;
    background: var(--app-hover);
  }
}

/* ── Chat bottom (input area fixed at bottom via flex) ── */
.chat-bottom {
  /* Keep the latest dev composer positioning so the input bar overlays the
     message stream consistently with the rest of the application shell. */
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 10;
  padding: 12px 16px 16px;
  .prompt-card {
    max-width: 790px;
    margin: 0 auto;
  }
}

:global(:root[data-theme='dark']) .prompt-card {
  background: rgba(39, 39, 42, 0.72);
}

@media (max-width: 900px) {
  .card-footer {
    height: auto;
    flex-wrap: wrap;
  }

  .footer-quick {
    order: 3;
    width: 100%;
    overflow-x: auto;
    padding-top: 4px;
  }

  .chat-bottom {
    padding-inline: 10px;
  }
}
</style>
