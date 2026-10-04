<template>
  <el-alert class="page-alert" :title="message" type="error" show-icon :closable="closable" @close="$emit('close')">
    <template #default>
      <el-button link type="primary" @click="$emit('retry')">{{ retryText }}</el-button>
    </template>
  </el-alert>
</template>

<script setup>
defineProps({
  message: { type: String, required: true },
  retryText: { type: String, default: '重试' },
  closable: { type: Boolean, default: false },
})

defineEmits(['retry', 'close'])
</script>
