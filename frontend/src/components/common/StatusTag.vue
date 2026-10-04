<template>
  <el-tag :type="type" :size="size" effect="light" :round="round">
    <slot>{{ label || status || '-' }}</slot>
  </el-tag>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
  label: { type: String, default: '' },
  size: { type: String, default: 'default' },
  round: { type: Boolean, default: false },
})

const type = computed(() => ({
  completed: 'success', success: 'success', ready: 'success',
  running: 'warning', processing: 'warning', pending: 'info', queued: 'info',
  failed: 'danger', error: 'danger', cancelled: 'info',
})[props.status] || 'info')
</script>
