<template>
  <section class="settings-panel">
    <div class="setting-row">
      <div>
        <h3>{{ text.appearance }}</h3>
        <p>{{ text.appearanceHelp }}</p>
      </div>
      <el-select
        v-model="theme"
        class="setting-select"
        popper-class="settings-select-popper"
        :aria-label="text.appearance"
      >
        <el-option :label="text.system" value="system" />
        <el-option :label="text.light" value="light" />
        <el-option :label="text.dark" value="dark" />
      </el-select>
    </div>

    <div class="setting-row">
      <div>
        <h3>{{ text.language }}</h3>
        <p>{{ text.languageHelp }}</p>
      </div>
      <el-select
        v-model="language"
        class="setting-select"
        popper-class="settings-select-popper"
        :aria-label="text.language"
      >
        <el-option label="简体中文" value="zh-CN" />
        <el-option label="English" value="en-US" />
      </el-select>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  text: {
    type: Object,
    required: true,
  },
})

const settingsStore = useSettingsStore()

const theme = computed({
  get: () => settingsStore.theme,
  set: (value) => settingsStore.setTheme(value),
})

const language = computed({
  get: () => settingsStore.language,
  set: (value) => settingsStore.setLanguage(value),
})
</script>

<style lang="scss" scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
}

.setting-row {
  min-height: 74px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 0;
  border-bottom: 1px solid var(--settings-border);

  h3 {
    margin: 0 0 4px;
    color: var(--settings-text);
    font-size: 14px;
    font-weight: 600;
  }

  p {
    margin: 0;
    color: var(--settings-muted);
    font-size: 12px;
    line-height: 1.5;
  }
}

.setting-select {
  width: 150px;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .setting-row {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }

  .setting-select {
    width: 100%;
  }
}
</style>
