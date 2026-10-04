<template>
  <form class="password-form" @submit.prevent="submit">
    <el-form label-position="top">
      <el-form-item :label="text.currentPassword" :error="errors.oldPassword">
        <el-input
          v-model="form.oldPassword"
          :type="show.old ? 'text' : 'password'"
          autocomplete="current-password"
          :aria-label="text.currentPassword"
        >
          <template #suffix>
            <button class="password-toggle" type="button" :aria-label="text.togglePassword" @click="show.old = !show.old">
              <el-icon><View v-if="!show.old" /><Hide v-else /></el-icon>
            </button>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item :label="text.newPassword" :error="errors.newPassword">
        <el-input
          v-model="form.newPassword"
          :type="show.next ? 'text' : 'password'"
          autocomplete="new-password"
          :aria-label="text.newPassword"
        >
          <template #suffix>
            <button class="password-toggle" type="button" :aria-label="text.togglePassword" @click="show.next = !show.next">
              <el-icon><View v-if="!show.next" /><Hide v-else /></el-icon>
            </button>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item :label="text.confirmPassword" :error="errors.confirmPassword">
        <el-input
          v-model="form.confirmPassword"
          :type="show.confirm ? 'text' : 'password'"
          autocomplete="new-password"
          :aria-label="text.confirmPassword"
        >
          <template #suffix>
            <button class="password-toggle" type="button" :aria-label="text.togglePassword" @click="show.confirm = !show.confirm">
              <el-icon><View v-if="!show.confirm" /><Hide v-else /></el-icon>
            </button>
          </template>
        </el-input>
      </el-form-item>

      <div class="password-actions">
        <el-button :disabled="loading" @click="$emit('cancel')">{{ text.cancel }}</el-button>
        <el-button type="primary" native-type="submit" :loading="loading">{{ text.save }}</el-button>
      </div>
    </el-form>
  </form>
</template>

<script setup>
import { reactive } from 'vue'
import { Hide, View } from '@element-plus/icons-vue'

defineProps({
  loading: { type: Boolean, default: false },
  text: { type: Object, required: true },
})

const emit = defineEmits(['submit', 'cancel'])

const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const errors = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const show = reactive({
  old: false,
  next: false,
  confirm: false,
})

function validate() {
  errors.oldPassword = form.oldPassword ? '' : '请输入当前密码'
  errors.newPassword = form.newPassword
    ? form.newPassword.length >= 8
      ? form.newPassword === form.oldPassword
        ? '新密码不能与当前密码相同'
        : ''
      : '新密码至少 8 位'
    : '请输入新密码'
  errors.confirmPassword = form.confirmPassword
    ? form.confirmPassword === form.newPassword
      ? ''
      : '两次新密码不一致'
    : '请确认新密码'
  return !errors.oldPassword && !errors.newPassword && !errors.confirmPassword
}

function clear() {
  form.oldPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  errors.oldPassword = ''
  errors.newPassword = ''
  errors.confirmPassword = ''
}

function submit() {
  if (!validate()) return
  emit('submit', {
    old_password: form.oldPassword,
    new_password: form.newPassword,
  }, clear)
}

defineExpose({ clear })
</script>

<style lang="scss" scoped>
.password-form {
  padding: 14px 0 4px;
}

.password-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  background: transparent;
  color: var(--settings-muted);
  cursor: pointer;
}

.password-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
