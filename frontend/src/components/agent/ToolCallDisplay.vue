<template>
  <div v-if="toolCall" class="tool-call">
    <!-- Agent label -->
    <div v-if="toolCall.agentLabel" class="agent-label">{{ toolCall.agentLabel }}</div>
    <!-- Running state -->
    <div v-if="toolCall.status === 'running'" class="tool-running">
      <div class="tool-dot" />
      <span>{{ toolCall.name ? `${text.running} (${toolCall.name})` : text.running }}</span>
    </div>

    <!-- Result state: keep this as a status trace only. Detection details are rendered by DetectionResultCard. -->
    <div v-else-if="toolCall.status === 'success'" class="tool-result">
      <div class="result-header">
        <el-icon :size="16" color="#67c23a"><CircleCheck /></el-icon>
        <span>{{ text.success }}</span>
      </div>
    </div>

    <!-- Error state -->
    <div v-else-if="toolCall.status === 'error'" class="tool-error">
      <el-icon :size="16"><CircleClose /></el-icon>
      <span>{{ text.error }}</span>
    </div>
  </div>
</template>

<script setup>
import { CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  toolCall: { type: Object, default: null },
})

const settingsStore = useSettingsStore()
const text = computed(() => settingsStore.isEnglish
  ? {
      running: 'Calling defect detection tool...',
      success: 'Defect detection tool succeeded',
      error: 'Tool call failed',
    }
  : {
      running: '正在调用缺陷检测工具…',
      success: '缺陷检测工具调用成功',
      error: '工具调用失败',
    },
)
</script>

<style lang="scss" scoped>
.tool-call {
  margin: 8px auto 16px;
  max-width: 780px;
  padding: 0 24px;
}

.agent-label {
  font-size: 12px;
  font-weight: 600;
  color: #8F8AB0;
  margin-bottom: 4px;
  padding-left: 2px;
  letter-spacing: 0.3px;
}

/* ── Running ── */
.tool-running {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: $text-secondary;
  padding: 8px 12px;
  background: var(--app-surface);
  border-radius: 8px;
  border: 1px solid var(--app-border);
}

.tool-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #e6a23c;
  animation: blink 1s ease-in-out infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}

/* ── Result ── */
.tool-result {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  overflow: hidden;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #67c23a;
  background: color-mix(in srgb, #67c23a 12%, var(--app-surface));
}

/* ── Error ── */
.tool-error {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #f56c6c;
  padding: 8px 12px;
  background: color-mix(in srgb, #f56c6c 12%, var(--app-surface));
  border-radius: 8px;
}
</style>
