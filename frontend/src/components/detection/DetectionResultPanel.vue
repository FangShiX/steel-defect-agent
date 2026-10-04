<template>
  <section class="result-panel">
    <div class="result-panel__heading">
      <div>
        <h3>{{ text.title }}</h3>
        <p>{{ result ? `${text.task} ${result.taskId}` : text.hint }}</p>
      </div>
      <el-tag v-if="result" type="success" effect="light">{{ text.done }}</el-tag>
    </div>

    <div v-loading="loading" class="result-panel__canvas">
      <div v-if="displayImage" class="image-stage" :style="stageStyle">
        <img :src="displayImage" :alt="text.previewAlt" />
        <template v-if="!result?.annotatedImageUrl">
          <div
            v-for="item in result?.objects || []"
            :key="item.id"
            class="detection-box"
            :style="boxStyle(item)"
          >
            <span>{{ item.classNameCn }} {{ formatPercent(item.confidence) }}</span>
          </div>
        </template>
      </div>
      <el-empty v-else :image-size="90" :description="text.empty" />
    </div>

    <template v-if="result">
      <div class="result-summary">
        <div><span>{{ text.defectCount }}</span><strong>{{ result.totalObjects }}</strong></div>
        <div><span>{{ text.inferenceTime }}</span><strong>{{ result.inferenceTimeMs.toFixed(0) }} ms</strong></div>
        <div><span>{{ text.maxConfidence }}</span><strong>{{ maxConfidence }}</strong></div>
      </div>

      <el-alert
        v-if="result.objects.length === 0"
        :title="text.noDefect"
        type="success"
        :closable="false"
        show-icon
      />
      <el-table v-else :data="result.objects" size="small" max-height="255">
        <el-table-column :label="text.defect" min-width="124">
          <template #default="{ row }">
            <strong>{{ row.classNameCn }}</strong>
            <small class="class-name">{{ row.className }}</small>
          </template>
        </el-table-column>
        <el-table-column :label="text.confidence" width="112">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(row.confidence * 100)"
              :stroke-width="7"
              :show-text="false"
            />
            <span class="confidence">{{ formatPercent(row.confidence) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="text.bbox" min-width="190">
          <template #default="{ row }">{{ row.bbox.map(Math.round).join(", ") }}</template>
        </el-table-column>
      </el-table>
    </template>
  </section>
</template>

<script setup>
import { computed } from "vue";
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  previewUrl: { type: String, default: "" },
  result: { type: Object, default: null },
  loading: { type: Boolean, default: false },
});

const settingsStore = useSettingsStore()

const text = computed(() => settingsStore.isEnglish ? {
  title: 'Detection Result',
  task: 'Task',
  hint: 'Upload a steel surface image to view annotated results',
  done: 'Completed',
  previewAlt: 'Steel surface detection preview',
  empty: 'Waiting for image',
  defectCount: 'Defects',
  inferenceTime: 'Inference time',
  maxConfidence: 'Max confidence',
  noDefect: 'No obvious defect detected',
  defect: 'Defect',
  confidence: 'Confidence',
  bbox: 'Bounding box [x1, y1, x2, y2]',
} : {
  title: '检测结果',
  task: '任务',
  hint: '上传钢铁表面图片后查看标注结果',
  done: '检测完成',
  previewAlt: '钢铁表面检测预览',
  empty: '等待检测图片',
  defectCount: '缺陷数量',
  inferenceTime: '推理耗时',
  maxConfidence: '最高置信度',
  noDefect: '未检测到明显缺陷',
  defect: '缺陷',
  confidence: '置信度',
  bbox: '边界框 [x1, y1, x2, y2]',
})

const displayImage = computed(
  () => props.result?.annotatedImageUrl || props.previewUrl || "",
);

const stageStyle = computed(() => ({
  aspectRatio:
    props.result?.imageWidth && props.result?.imageHeight
      ? `${props.result.imageWidth} / ${props.result.imageHeight}`
      : "16 / 10",
}));

const maxConfidence = computed(() => {
  const max = Math.max(0, ...(props.result?.objects || []).map((item) => item.confidence));
  return formatPercent(max);
});

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function boxStyle(item) {
  const [left, top, width, height] = item.bboxPercent || [10, 10, 30, 20];
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${width}%`,
    height: `${height}%`,
  };
}
</script>

<style lang="scss" scoped>
.result-panel {
  padding: 20px;
  border: 1px solid #e7ebf1;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(28, 39, 60, 0.05);
}

.result-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;

  h3 {
    margin: 0;
    color: #1f2937;
    font-size: 16px;
  }

  p {
    margin: 4px 0 0;
    color: $text-secondary;
    font-size: 12px;
  }
}

.result-panel__canvas {
  display: grid;
  min-height: 310px;
  place-items: center;
  overflow: hidden;
  border: 1px dashed #d7dee8;
  border-radius: 12px;
  background: #f7f9fc;
}

.image-stage {
  position: relative;
  width: 100%;
  max-height: 430px;
  overflow: hidden;
  background: #111827;

  img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
}

.detection-box {
  position: absolute;
  border: 2px solid #fbbf24;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.28);

  span {
    position: absolute;
    top: -24px;
    left: -2px;
    padding: 3px 7px;
    border-radius: 4px 4px 4px 0;
    background: #fbbf24;
    color: #172033;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
  }
}

.result-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 14px 0;

  div {
    padding: 11px 13px;
    border-radius: 9px;
    background: #f7f9fc;
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
    color: #172033;
    font-size: 16px;
  }
}

.class-name {
  display: block;
  color: $text-secondary;
}

.confidence {
  display: block;
  margin-top: 3px;
  color: $text-regular;
  font-size: 11px;
}

@media (max-width: 640px) {
  .result-summary {
    grid-template-columns: 1fr;
  }
}
</style>
