<template>
  <div class="profile-field">
    <div class="field-main">
      <h3>{{ label }}</h3>
      <p v-if="!editing">{{ displayValue || emptyText }}</p>
      <div v-else class="field-editor">
        <el-input
          ref="inputRef"
          v-model="draft"
          :type="type"
          :placeholder="label"
          :aria-label="label"
          :aria-describedby="error ? errorId : undefined"
          @keyup.enter="handleSave"
        />
        <p v-if="error" :id="errorId" class="field-error">{{ error }}</p>
      </div>
    </div>

    <div class="field-actions">
      <template v-if="editing">
        <el-button size="small" :loading="loading" @click="handleSave">{{ saveText }}</el-button>
        <el-button size="small" :disabled="loading" @click="cancel">{{ cancelText }}</el-button>
      </template>
      <el-button v-else size="small" text @click="startEdit">{{ editText }}</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, default: '' },
  type: { type: String, default: 'text' },
  loading: { type: Boolean, default: false },
  validator: { type: Function, default: null },
  emptyText: { type: String, default: '未设置' },
  editText: { type: String, default: '编辑' },
  saveText: { type: String, default: '保存' },
  cancelText: { type: String, default: '取消' },
})

const emit = defineEmits(['save'])

const editing = ref(false)
const draft = ref('')
const error = ref('')
const inputRef = ref(null)
const errorId = `profile-error-${Math.random().toString(36).slice(2)}`

const displayValue = computed(() => props.value)

function startEdit() {
  draft.value = props.value || ''
  error.value = ''
  editing.value = true
  nextTick(() => inputRef.value?.focus?.())
}

function cancel() {
  editing.value = false
  error.value = ''
}

async function handleSave() {
  const value = draft.value.trim()
  const validation = props.validator?.(value)
  if (validation) {
    error.value = validation
    return
  }
  error.value = ''
  emit('save', value, () => {
    editing.value = false
  })
}
</script>

<style lang="scss" scoped>
.profile-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--settings-border);
}

.field-main {
  flex: 1;
  min-width: 0;

  h3 {
    margin: 0 0 5px;
    color: var(--settings-text);
    font-size: 14px;
    font-weight: 600;
  }

  p {
    margin: 0;
    color: var(--settings-muted);
    font-size: 13px;
    word-break: break-word;
  }
}

.field-editor {
  max-width: 320px;
}

.field-error {
  margin-top: 6px !important;
  color: #f56c6c !important;
}

.field-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .profile-field {
    align-items: stretch;
    flex-direction: column;
  }

  .field-editor {
    max-width: none;
  }

  .field-actions {
    justify-content: flex-end;
  }
}
</style>
