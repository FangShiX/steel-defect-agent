<template>
  <section class="settings-panel">
    <EditProfileField
      :label="text.username"
      :value="userStore.user?.username || ''"
      :loading="profileLoading === 'username'"
      :validator="validateUsername"
      :edit-text="text.edit"
      :save-text="text.save"
      :cancel-text="text.cancel"
      @save="(value, done) => saveProfile({ username: value }, done)"
    />

    <EditProfileField
      :label="text.email"
      :value="userStore.user?.email || ''"
      type="email"
      :loading="profileLoading === 'email'"
      :validator="validateEmail"
      :edit-text="text.edit"
      :save-text="text.save"
      :cancel-text="text.cancel"
      @save="(value, done) => saveProfile({ email: value }, done)"
    />

    <div class="password-section">
      <div class="password-header">
        <div>
          <h3>{{ text.password }}</h3>
          <p>{{ text.passwordHelp }}</p>
        </div>
        <el-button v-if="!passwordOpen" size="small" @click="passwordOpen = true">
          {{ text.changePassword }}
        </el-button>
      </div>

      <ChangePasswordForm
        v-if="passwordOpen"
        :text="text"
        :loading="passwordLoading"
        @cancel="passwordOpen = false"
        @submit="savePassword"
      />
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import EditProfileField from './EditProfileField.vue'
import ChangePasswordForm from './ChangePasswordForm.vue'

defineProps({
  text: {
    type: Object,
    required: true,
  },
})

const userStore = useUserStore()
const profileLoading = ref('')
const passwordLoading = ref(false)
const passwordOpen = ref(false)

function validateUsername(value) {
  if (!value) return '用户名不能为空'
  if (value.length > 50) return '用户名不能超过 50 个字符'
  return ''
}

function validateEmail(value) {
  if (!value) return '邮箱不能为空'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return '请输入有效邮箱'
  return ''
}

async function saveProfile(payload, done) {
  const key = Object.keys(payload)[0]
  if (profileLoading.value) return
  profileLoading.value = key
  try {
    await userStore.updateProfile(payload)
    done()
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  } finally {
    profileLoading.value = ''
  }
}

async function savePassword(payload, clear) {
  if (passwordLoading.value) return
  passwordLoading.value = true
  try {
    await userStore.changePassword(payload)
    clear()
    passwordOpen.value = false
    ElMessage.success('密码修改成功')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '密码修改失败')
  } finally {
    passwordLoading.value = false
  }
}
</script>

<style lang="scss" scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
}

.password-section {
  padding: 14px 0;
}

.password-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;

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
  }
}

@media (max-width: 640px) {
  .password-header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
