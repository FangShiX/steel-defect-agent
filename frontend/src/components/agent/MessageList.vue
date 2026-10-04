<template>
  <div class="message-list">
    <div v-if="!messages.length && !isStreaming" class="empty-state">
      <p>{{ text.empty }}</p>
    </div>

    <MessageItem
      v-for="(message, index) in messages"
      :key="message.id"
      :message="message"
      :is-last-streaming="isStreaming && index === messages.length - 1 && message.role === 'assistant'"
      @regenerate="(msg) => $emit('regenerate', msg)"
    />

    <!-- Thinking indicator -->
    <div v-if="showThinking" class="thinking-row">
      <ThinkingIndicator />
    </div>

  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import MessageItem from './MessageItem.vue'
import ThinkingIndicator from './ThinkingIndicator.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  isStreaming: { type: Boolean, default: false },
})

const settingsStore = useSettingsStore()
const text = computed(() => settingsStore.isEnglish
  ? { empty: 'Start a chat and ask about steel surface defects.' }
  : { empty: '开始对话，询问钢铁表面缺陷相关问题。' },
)

defineEmits(['regenerate'])

const showThinking = computed(() => {
  if (!props.isStreaming) return false
  const last = props.messages[props.messages.length - 1]
  return last?.role === 'assistant' && !last?.content
})
</script>

<style lang="scss" scoped>
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 0;
  background: var(--app-bg);
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #a3a3a3;
  font-size: 14px;
  text-align: center;
}

.thinking-row {
  width: calc(100% - 48px);
  max-width: 780px;
  margin: 0 auto;
  padding: 8px 0;
  box-sizing: border-box;
}
</style>
