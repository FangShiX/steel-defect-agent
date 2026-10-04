<template>
  <div class="thinking-indicator">
    <div class="dot-matrix">
      <span
        v-for="i in 16"
        :key="i"
        class="dot"
        :class="{ active: activeDots.has(i - 1) }"
      />
    </div>
    <span class="thinking-text">正在分析…</span>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const activeDots = ref(new Set())
const patterns = [
  [[0], [1], [2], [3], [7], [11], [15], [14], [13], [12], [8], [4], [5], [6], [10], [9]],
  [[0, 4, 8, 12], [1, 5, 9, 13], [2, 6, 10, 14], [3, 7, 11, 15]],
  [[5, 6, 9, 10], [1, 4, 7, 8, 11, 14], [0, 3, 12, 15], [1, 4, 7, 8, 11, 14], [5, 6, 9, 10]],
  [[0], [1, 4], [2, 5, 8], [3, 6, 9, 12], [7, 10, 13], [11, 14], [15]],
]

let patternIndex = 0
let stepIndex = 0
let timer = null

function nextStep() {
  const pattern = patterns[patternIndex]
  if (!pattern) return
  activeDots.value = new Set(pattern[stepIndex])
  stepIndex++
  if (stepIndex >= pattern.length) {
    stepIndex = 0
    patternIndex = (patternIndex + 1) % patterns.length
  }
}

onMounted(() => {
  nextStep()
  timer = setInterval(nextStep, 120)
})

onUnmounted(() => {
  clearInterval(timer)
})
</script>

<style lang="scss" scoped>
.thinking-indicator {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  margin: 4px 0;
  border-radius: 8px;
  background: #fff;
  box-shadow: $shadow-sm;
  max-width: 200px;
}

.dot-matrix {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 2px;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.dot {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 1px;
  background: #c0c4cc;
  transition: opacity 0.1s;
  opacity: 0.2;

  &.active {
    opacity: 1;
    background: #8F8AB0;
  }
}

.thinking-text {
  font-size: 13px;
  color: $text-secondary;
  white-space: nowrap;
}
</style>
