<template>
  <nav class="settings-sidebar" aria-label="设置分类">
    <button
      v-for="item in items"
      :key="item.key"
      :class="['settings-nav-item', { active: model === item.key }]"
      type="button"
      @click="model = item.key"
    >
      <el-icon><component :is="item.icon" /></el-icon>
      <span>{{ labels[item.key] }}</span>
    </button>
  </nav>
</template>

<script setup>
import { Setting, User, Lock } from '@element-plus/icons-vue'

const model = defineModel({ default: 'general' })

defineProps({
  labels: {
    type: Object,
    required: true,
  },
})

const items = [
  { key: 'general', icon: Setting },
  { key: 'account', icon: User },
  { key: 'sessions', icon: Lock },
]
</script>

<style lang="scss" scoped>
.settings-sidebar {
  width: 170px;
  flex-shrink: 0;
  padding: 58px 8px 16px;
  border-right: 1px solid var(--settings-border);
}

.settings-nav-item {
  width: 100%;
  height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--settings-text);
  font-size: 14px;
  cursor: pointer;
  text-align: left;

  &:hover {
    background: var(--settings-hover);
  }

  &.active {
    background: var(--settings-active);
    font-weight: 600;
  }
}

@media (max-width: 640px) {
  .settings-sidebar {
    width: auto;
    display: flex;
    gap: 6px;
    padding: 52px 12px 10px;
    border-right: 0;
    border-bottom: 1px solid var(--settings-border);
  }

  .settings-nav-item {
    width: auto;
    flex: 1;
    justify-content: center;
  }
}
</style>
