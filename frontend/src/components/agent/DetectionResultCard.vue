<template>
  <div class="detection-card">
    <div class="card-header">
      <div>
        <strong>{{ title }}</strong>
        <p>{{ subtitle }}</p>
        <router-link
          v-if="taskLinkId"
          :to="{ path: '/history', query: { task: taskLinkId } }"
          class="task-link"
        >
          {{ text.openTask }} #{{ taskLinkId }}
        </router-link>
      </div>
      <el-tag type="success" effect="light">{{ text.done }}</el-tag>
    </div>

    <div :class="['result-overview', { 'without-image': !displayImages.length }]">
      <div v-if="displayImages.length" :class="['result-gallery', { single: displayImages.length === 1 }]">
        <figure v-for="(image, index) in displayImages" :key="`${image.src}-${index}`" class="result-figure">
          <el-image
            :src="image.src"
            :preview-src-list="previewImages"
            :initial-index="index"
            fit="contain"
            class="result-image"
          />
          <figcaption v-if="displayImages.length > 1">{{ image.label || `${text.image} ${index + 1}` }}</figcaption>
        </figure>
      </div>

      <div class="summary">
        <div>
          <span>{{ text.imageCount }}</span>
          <strong>{{ imageCount }}</strong>
        </div>
        <div>
          <span>{{ text.defectCount }}</span>
          <strong>{{ objectCount }}</strong>
        </div>
        <div>
          <span>{{ text.maxConfidence }}</span>
          <strong>{{ maxConfidence }}</strong>
        </div>
      </div>
    </div>

    <el-table v-if="tableRows.length" :data="tableRows" size="small" max-height="240">
      <el-table-column prop="fileName" :label="text.image" min-width="120" />
      <el-table-column prop="className" :label="text.defectType" min-width="110" />
      <el-table-column :label="text.confidence" width="100">
        <template #default="{ row }">{{ formatPercent(row.confidence) }}</template>
      </el-table-column>
    </el-table>

    <el-empty v-else :image-size="64" :description="text.noDefect" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  result: {
    type: Object,
    required: true,
  },
  previewUrl: {
    type: String,
    default: '',
  },
})

const settingsStore = useSettingsStore()
const text = computed(() => settingsStore.isEnglish ? {
  done: 'Completed',
  imageCount: 'Images',
  defectCount: 'Defects',
  maxConfidence: 'Max confidence',
  image: 'Image',
  defectType: 'Defect type',
  confidence: 'Confidence',
  noDefect: 'No obvious defect detected',
  openTask: 'Open task',
  batchTitle: 'Batch Detection Result',
  singleTitle: 'Single-image Detection Result',
  task: 'Task',
  unknownDefect: 'Unknown defect',
} : {
  done: '检测完成',
  imageCount: '图片数量',
  defectCount: '缺陷数量',
  maxConfidence: '最高置信度',
  image: '图片',
  defectType: '缺陷类型',
  confidence: '置信度',
  noDefect: '未检测到明显缺陷',
  openTask: '打开任务',
  batchTitle: '批量检测结果',
  singleTitle: '单图检测结果',
  task: '任务',
  unknownDefect: '未知缺陷',
})

const isBatch = computed(() => Array.isArray(props.result.items))

const title = computed(() => (isBatch.value ? text.value.batchTitle : text.value.singleTitle))

const subtitle = computed(() => {
  if (isBatch.value) return `任务 ${props.result.taskId || '-'}`
  return props.result.fileName || `${text.value.task} ${props.result.taskId || '-'}`
})

const taskLinkId = computed(() => {
  const value = Number(props.result.taskId ?? props.result.task_id)
  return Number.isInteger(value) && value > 0 ? value : null
})

const displayImages = computed(() => {
  if (isBatch.value) {
    const images = (props.result.items || [])
      .map((item, index) => ({
        src: item.annotatedImageUrl || item.originalImageUrl || '',
        label: item.fileName || `${text.value.image} ${index + 1}`,
      }))
      .filter(item => item.src)
    if (images.length) return images
    return props.previewUrl ? [{ src: props.previewUrl, label: '' }] : []
  }
  const src = props.result.annotatedImageUrl || props.result.originalImageUrl || props.previewUrl
  return src ? [{ src, label: props.result.fileName || '' }] : []
})

const previewImages = computed(() => displayImages.value.map(item => item.src))

const imageCount = computed(() => {
  if (isBatch.value) return props.result.items?.length || props.result.successCount || 0
  return props.result.totalImages || 1
})

const objectCount = computed(() => {
  if (isBatch.value) {
    return (props.result.items || []).reduce((sum, item) => sum + Number(item.totalObjects || 0), 0)
  }
  return props.result.totalObjects || props.result.objects?.length || 0
})

const tableRows = computed(() => {
  if (isBatch.value) {
    return (props.result.items || []).flatMap((item) => {
      if (!item.objects?.length) {
        return [{
          fileName: item.fileName || '-',
          className: item.error || text.value.noDefect,
          confidence: 0,
        }]
      }
      return item.objects.map((object) => ({
        fileName: item.fileName || '-',
        className: object.classNameCn || object.className || text.value.unknownDefect,
        confidence: object.confidence,
      }))
    })
  }

  return (props.result.objects || []).map((object) => ({
    fileName: props.result.fileName || '-',
    className: object.classNameCn || object.className || text.value.unknownDefect,
    confidence: object.confidence,
  }))
})

const maxConfidence = computed(() => {
  const values = tableRows.value.map((row) => Number(row.confidence || 0))
  return formatPercent(Math.max(0, ...values))
})

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}
</script>

<style lang="scss" scoped>
.detection-card {
  margin-top: 12px;
  padding: 16px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
  box-shadow: var(--app-shadow);
}

.card-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  strong {
    color: var(--app-text);
    font-size: 15px;
  }

  p {
    margin: 4px 0 0;
    color: $text-secondary;
    font-size: 12px;
  }
}

.task-link {
  display: inline-block;
  margin-top: 6px;
  color: var(--app-primary);
  font-size: 12px;
}

.result-overview {
  display: grid;
  grid-template-columns: minmax(220px, 420px) minmax(150px, 1fr);
  align-items: stretch;
  gap: 12px;
  margin-bottom: 12px;

  &.without-image {
    grid-template-columns: 1fr;
  }
}

.result-gallery {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;

  &.single {
    grid-template-columns: minmax(0, 1fr);
  }
}

.result-figure {
  min-width: 0;
  margin: 0;
}

.result-image {
  display: block;
  width: 100%;
  height: 180px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-subtle);
  overflow: hidden;

  :deep(.el-image__inner) {
    width: 100%;
    height: 100%;
  }
}

.result-gallery.single .result-image {
  height: clamp(200px, 30vw, 280px);
}

.result-figure figcaption {
  margin-top: 5px;
  overflow: hidden;
  color: $text-secondary;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;

  div {
    padding: 10px 12px;
    border-radius: 9px;
    background: var(--app-subtle);
  }

  span,
  strong {
    display: block;
  }

  span {
    color: $text-secondary;
    font-size: 11px;
  }

  strong {
    margin-top: 3px;
    color: var(--app-text);
    font-size: 16px;
  }
}

@media (max-width: 640px) {
  .result-overview {
    grid-template-columns: 1fr;
  }

  .result-gallery {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .result-image,
  .result-gallery.single .result-image {
    height: 180px;
  }

  .summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
