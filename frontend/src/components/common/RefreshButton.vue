<template>
  <button class="period-trigger refresh-btn" :disabled="loading" @click="$emit('click')">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: loading }"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>
    <span class="period-val">{{ label }}</span>
  </button>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  loading: { type: Boolean, default: false },
})

defineEmits(['click'])
</script>
