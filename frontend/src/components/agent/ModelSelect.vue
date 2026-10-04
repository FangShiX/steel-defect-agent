<template>
  <el-popover
    placement="top-start"
    :width="220"
    trigger="click"
    :show-arrow="false"
  >
    <template #reference>
      <button class="model-btn">
        <span>{{ currentLabel }}</span>
        <el-icon :size="12"><ArrowDown /></el-icon>
      </button>
    </template>

    <div class="model-list">
        <div v-if="llmStore.loading" class="model-hint">{{ text.loading }}</div>
      <template v-else>
        <button
          v-for="m in options"
          :key="m.value"
          :class="['model-item', { active: model === m.value }]"
          @click="model = m.value"
        >
          <div class="model-info">
            <span class="model-name">{{ m.label }}</span>
            <span class="model-provider">{{ m.ownedBy }}</span>
          </div>
          <el-icon v-if="model === m.value" :size="14" color="#8F8AB0"><Check /></el-icon>
        </button>
        <div v-if="options.length === 0 && llmStore.error" class="model-hint error">
          {{ text.loadFailed }}
        </div>
      </template>
    </div>
  </el-popover>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown, Check } from '@element-plus/icons-vue'
import { useLlmStore } from '@/stores/llm'
import { DEFAULT_LLM_MODEL_VALUE } from '@/stores/llm'
import { useSettingsStore } from '@/stores/settings'

const llmStore = useLlmStore()
const settingsStore = useSettingsStore()

const model = defineModel({ default: useLlmStore().defaultModel })

const text = computed(() => settingsStore.isEnglish ? {
  defaultModel: 'Default chat model',
  selectModel: 'Select model',
  loading: 'Loading...',
  loadFailed: 'Failed to load models',
} : {
  defaultModel: '后端默认对话模型',
  selectModel: '选择模型',
  loading: '加载中…',
  loadFailed: '获取模型列表失败',
})

const options = computed(() => llmStore.modelOptions.map((option) => {
  if (option.value !== DEFAULT_LLM_MODEL_VALUE) return option
  return { ...option, label: text.value.defaultModel }
}))

const currentLabel = computed(() => {
  if (model.value === DEFAULT_LLM_MODEL_VALUE) {
    return text.value.defaultModel
  }
  const found = options.value.find(m => m.value === model.value)
  return found?.label || model.value || text.value.selectModel
})

</script>

<style lang="scss" scoped>
.model-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 36px;
  padding: 0 12px;
  border: 0;
  border-radius: 18px;
  background: transparent;
  color: var(--app-muted);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: rgba(0,0,0,0.06);
    color: var(--app-text);
  }
}

.model-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px;
  max-height: 280px;
  overflow-y: auto;
}

.model-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: 13px;
  color: var(--app-text);
  cursor: pointer;
  transition: background 0.1s;
  width: 100%;
  text-align: left;

  &:hover {
    background: var(--app-hover);
  }

  &.active {
    color: #8F8AB0;
  }
}

.model-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
}

.model-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-provider {
  font-size: 11px;
  color: #999;
}

.model-hint {
  padding: 8px 10px;
  font-size: 12px;
  color: #999;
  text-align: center;

  &.error {
    color: #e5534b;
  }
}
</style>
