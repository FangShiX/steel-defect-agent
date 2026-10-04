<template>
  <div class="quick-detect-bar">
    <button class="quick-detect-btn" :disabled="disabled" @click="$emit('single')">
      {{ labels.single }}
    </button>
    <button class="quick-detect-btn" :disabled="disabled" @click="$emit('batch')">
      {{ labels.batch }}
    </button>
    <button class="quick-detect-btn" :disabled="disabled" @click="$emit('zip')">
      {{ labels.zip }}
    </button>
    <button class="quick-detect-btn" :disabled="disabled" @click="$emit('video')">
      {{ labels.video }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
  labels: {
    type: Object,
    default: () => ({
      single: '单图检测',
      batch: '批量图片检测',
      zip: 'ZIP 检测',
      video: '视频检测',
    }),
  },
})

defineEmits(['single', 'batch', 'zip', 'video'])
</script>

<style lang="scss" scoped>
.quick-detect-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.quick-detect-btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid #e0e0e0;
  border-radius: 18px;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;

  &:hover:not(:disabled) {
    border-color: #8f8ab0;
    color: #8f8ab0;
    background: var(--app-hover);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}
</style>
