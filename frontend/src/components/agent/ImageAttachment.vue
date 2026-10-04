<template>
  <div
    :class="['image-attachment', { 'is-dragover': isDragover }]"
    @dragenter.prevent="handleDragEnter"
    @dragover.prevent="handleDragEnter"
    @dragleave.prevent="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <input
      ref="fileInputRef"
      type="file"
      accept="image/png,image/jpeg"
      hidden
      @change="handleFileChange"
    />

    <div class="drop-zone" @click="fileInputRef.click()">
      <el-button>选择图片</el-button>
      <span>或将 JPG/PNG 图片拖拽到这里</span>
    </div>

    <div v-if="previewUrl" class="preview">
      <img :src="previewUrl" alt="待分析图片" />
      <el-button link type="danger" @click="$emit('remove')">
        移除
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

defineProps({
  previewUrl: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select', 'remove'])
const fileInputRef = ref(null)
const isDragover = ref(false)

function handleFileChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''

  if (!file) return
  handleSelectedFile(file)
}

function handleSelectedFile(file) {
  const allowedTypes = ['image/jpeg', 'image/png']
  const maxSize = 10 * 1024 * 1024

  if (!allowedTypes.includes(file.type)) {
    ElMessage.error('仅支持 JPG、JPEG 和 PNG 图片')
    return
  }

  if (file.size > maxSize) {
    ElMessage.error('图片大小不能超过 10MB')
    return
  }

  emit('select', file)
}

function handleDragEnter() {
  isDragover.value = true
}

function handleDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    isDragover.value = false
  }
}

function handleDrop(event) {
  isDragover.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleSelectedFile(file)
}
</script>

<style lang="scss" scoped>
.image-attachment {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  transition: background 0.2s;

  &.is-dragover {
    background: #ecf5ff;
  }
}

.drop-zone {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 8px 12px;
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  color: $text-secondary;
  cursor: pointer;
  transition:
    border-color 0.2s,
    background 0.2s;

  &:hover {
    border-color: $primary-color;
    background: #f5f9ff;
  }
}

.preview {
  display: flex;
  align-items: center;
  gap: 8px;

  img {
    width: 72px;
    height: 48px;
    border-radius: 6px;
    object-fit: cover;
    border: 1px solid #dcdfe6;
  }
}
</style>
