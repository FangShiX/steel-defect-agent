<template>
  <div class="login-page">
    <div class="login-wrapper">
      <!-- Left — Silk brand panel -->
      <div class="login-left">
        <div class="silk-bg">
          <SilkCanvas :speed="6.5" :scale="0.8" color="#1f1f1f" :noise-intensity="0" :rotation="0" />
        </div>
        <div class="silk-overlay" />

        <div class="brand-text">
          <h2>
            让AI
            <br />
            看见缺陷。
          </h2>
          <p>
            钢铁表面缺陷检测智能体平台
            <br />
            基于 YOLOv11,智能识别与训练一站式。
          </p>
        </div>
      </div>

      <!-- Right — login form -->
      <div class="login-right">
        <div class="form-container">

          <div class="form-header">
            <h1>{{ text.heading }}</h1>
            <p>{{ text.subtitle }}</p>
          </div>

          <el-form
            ref="formRef"
            :model="loginForm"
            :rules="loginRules"
            label-width="0"
            @submit.prevent="handleLogin"
          >
            <el-form-item prop="username">
              <label class="field-label">{{ text.username }}</label>
              <el-input
                v-model="loginForm.username"
                :placeholder="text.usernamePlaceholder"
                :prefix-icon="User"
                autofocus
                autocomplete="username"
              />
            </el-form-item>

            <el-form-item prop="password">
              <div class="field-label-row">
                <label class="field-label">{{ text.password }}</label>
                <button type="button" class="forgot-link" @click="forgotOpen = true">{{ text.forgot }}</button>
              </div>
              <div class="pwd-wrap">
                <el-input
                  v-model="loginForm.password"
                  :type="showPwd ? 'text' : 'password'"
                  placeholder="••••••••"
                  :prefix-icon="Lock"
                  autocomplete="current-password"
                  @keyup.enter="handleLogin"
                />
                <button
                  type="button"
                  class="pwd-toggle"
                  :aria-label="showPwd ? '隐藏密码' : '显示密码'"
                  @click="showPwd = !showPwd"
                >
                  <el-icon><Hide v-if="showPwd" /><View v-else /></el-icon>
                </button>
              </div>
            </el-form-item>

            <div v-if="errorMsg" class="error-banner">
              {{ errorMsg }}
            </div>

            <el-button
              type="primary"
              class="submit-btn"
              :loading="loading"
              @click="handleLogin"
            >
              {{ loading ? text.loggingIn : text.login }}
            </el-button>
          </el-form>

          <div class="form-footer">
            <span>{{ text.noAccount }}</span>
            <router-link to="/register">{{ text.register }}</router-link>
          </div>
        </div>
      </div>
    </div>

    <transition name="toast-fade">
      <div v-if="showSuccess" class="login-toast">
        <svg class="login-toast-wave" viewBox="0 0 1440 320" xmlns="http://www.w3.org/2000/svg"><path d="M0,256L11.4,240C22.9,224,46,192,69,192C91.4,192,114,224,137,234.7C160,245,183,235,206,213.3C228.6,192,251,160,274,149.3C297.1,139,320,149,343,181.3C365.7,213,389,267,411,282.7C434.3,299,457,277,480,250.7C502.9,224,526,192,549,181.3C571.4,171,594,181,617,208C640,235,663,277,686,256C708.6,235,731,149,754,122.7C777.1,96,800,128,823,165.3C845.7,203,869,245,891,224C914.3,203,937,117,960,112C982.9,107,1006,181,1029,197.3C1051.4,213,1074,171,1097,144C1120,117,1143,107,1166,133.3C1188.6,160,1211,224,1234,218.7C1257.1,213,1280,139,1303,133.3C1325.7,128,1349,192,1371,192C1394.3,192,1417,128,1429,96L1440,64L1440,320L1428.6,320C1417.1,320,1394,320,1371,320C1348.6,320,1326,320,1303,320C1280,320,1257,320,1234,320C1211.4,320,1189,320,1166,320C1142.9,320,1120,320,1097,320C1074.3,320,1051,320,1029,320C1005.7,320,983,320,960,320C937.1,320,914,320,891,320C868.6,320,846,320,823,320C800,320,777,320,754,320C731.4,320,709,320,686,320C662.9,320,640,320,617,320C594.3,320,571,320,549,320C525.7,320,503,320,480,320C457.1,320,434,320,411,320C388.6,320,366,320,343,320C320,320,297,320,274,320C251.4,320,229,320,206,320C182.9,320,160,320,137,320C114.3,320,91,320,69,320C45.7,320,23,320,11,320L0,320Z" fill-opacity="1"/></svg>
        <div class="login-toast-icon">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="currentColor" stroke="currentColor"><path d="M256 48a208 208 0 1 1 0 416 208 208 0 1 1 0-416zm0 464A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM369 209c9.4-9.4 9.4-24.6 0-33.9s-24.6-9.4-33.9 0l-111 111-47-47c-9.4-9.4-24.6-9.4-33.9 0s-9.4 24.6 0 33.9l64 64c9.4 9.4 24.6 9.4 33.9 0L369 209z"/></svg>
        </div>
        <div class="login-toast-text">
          <p class="login-toast-title">登录成功</p>
          <p class="login-toast-sub">欢迎回来</p>
        </div>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 15" fill="currentColor" class="login-toast-close" @click="showSuccess = false"><path d="M11.7816 4.03157C12.0062 3.80702 12.0062 3.44295 11.7816 3.2184C11.5571 2.99385 11.193 2.99385 10.9685 3.2184L7.50005 6.68682L4.03164 3.2184C3.80708 2.99385 3.44301 2.99385 3.21846 3.2184C2.99391 3.44295 2.99391 3.80702 3.21846 4.03157L6.68688 7.49999L3.21846 10.9684C2.99391 11.193 2.99391 11.557 3.21846 11.7816C3.44301 12.0061 3.80708 12.0061 4.03164 11.7816L7.50005 8.31316L10.9685 11.7816C11.193 12.0061 11.5571 12.0061 11.7816 11.7816C12.0062 11.557 12.0062 11.193 11.7816 10.9684L8.31322 7.49999L11.7816 4.03157Z" clip-rule="evenodd" fill-rule="evenodd"/></svg>
      </div>
    </transition>
    <el-dialog v-model="forgotOpen" :title="text.resetTitle" width="420px">
      <el-form label-position="top">
        <el-form-item :label="text.email">
          <el-input v-model="resetForm.email" autocomplete="email" />
        </el-form-item>
        <el-button type="primary" :loading="resetLoading" @click="requestReset">{{ text.sendReset }}</el-button>
        <el-divider />
        <el-form-item :label="text.resetToken">
          <el-input v-model="resetForm.token" autocomplete="one-time-code" />
        </el-form-item>
        <el-form-item :label="text.newPassword">
          <el-input v-model="resetForm.newPassword" type="password" autocomplete="new-password" />
        </el-form-item>
        <el-button :loading="resetLoading" @click="confirmReset">{{ text.setPassword }}</el-button>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, View, Hide } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useSettingsStore } from '@/stores/settings'
import SilkCanvas from '@/components/SilkCanvas.vue'
import { confirmPasswordResetApi, requestPasswordResetApi } from '@/api/auth'
import { getApiErrorMessage } from '@/utils/apiError'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const settingsStore = useSettingsStore()

const text = computed(() => settingsStore.isEnglish ? {
  heading: 'Welcome back', subtitle: 'Enter your account and password to continue.', username: 'Username', usernamePlaceholder: 'Enter your username', password: 'Password', forgot: 'Forgot password?', login: 'Sign in', loggingIn: 'Signing in…', noAccount: "Don't have an account?", register: 'Create account', resetTitle: 'Reset password', email: 'Email', resetToken: 'Reset token', newPassword: 'New password', sendReset: 'Send reset request', setPassword: 'Set new password', loginSuccess: 'Signed in successfully', loginFailed: 'Sign-in failed. Please check your credentials.', emailRequired: 'Enter your email', resetRequested: 'If the email is registered, reset instructions will be sent.', resetSuccess: 'Password reset. Please sign in.', resetInputRequired: 'Enter the reset token and new password', passwordMin: 'Password must be at least 6 characters', usernameRequired: 'Enter your username', usernameLength: 'Username must be 3-50 characters', passwordRequired: 'Enter your password', resetFailed: 'Password reset failed. Check whether the token is valid',
} : {
  heading: '欢迎回来', subtitle: '输入账号与密码继续。', username: '用户名', usernamePlaceholder: '输入您的用户名', password: '密码', forgot: '忘记密码？', login: '登录', loggingIn: '登录中…', noAccount: '还没有账号？', register: '立即注册', resetTitle: '找回密码', email: '邮箱', resetToken: '重置令牌', newPassword: '新密码', sendReset: '发送重置请求', setPassword: '设置新密码', loginSuccess: '登录成功', loginFailed: '登录失败，请检查账号或密码', emailRequired: '请输入邮箱', resetRequested: '如果该邮箱已注册，重置链接将发送到您的邮箱。', resetSuccess: '密码重置成功，请重新登录。', resetInputRequired: '请输入重置令牌和新密码', passwordMin: '密码至少需要 6 个字符', usernameRequired: '请输入用户名', usernameLength: '用户名需要 3-50 个字符', passwordRequired: '请输入密码', resetFailed: '密码重置失败，请检查令牌是否有效',
})

const formRef = ref(null)
const loading = ref(false)
const showPwd = ref(false)
const errorMsg = ref('')
const showSuccess = ref(false)
const forgotOpen = ref(false)
const resetLoading = ref(false)
const resetForm = reactive({ email: '', token: '', newPassword: '' })

onMounted(() => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (token) {
    resetForm.token = token
    forgotOpen.value = true
  }
})

const loginForm = reactive({
  username: '',
  password: '',
})

const loginRules = computed(() => ({
  username: [
    { required: true, message: text.value.usernameRequired, trigger: 'blur' },
    { min: 3, max: 50, message: text.value.usernameLength, trigger: 'blur' },
  ],
  password: [
    { required: true, message: text.value.passwordRequired, trigger: 'blur' },
    { min: 6, message: text.value.passwordMin, trigger: 'blur' },
  ],
}))

async function handleLogin() {
  errorMsg.value = ''
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userStore.login({
      username: loginForm.username,
      password: loginForm.password,
    })

    showSuccess.value = true
    setTimeout(() => {
      const redirect = route.query.redirect || '/'
      router.push(redirect)
    }, 1200)
  } catch (err) {
    errorMsg.value = getApiErrorMessage(err, text.value.loginFailed)
  } finally {
    loading.value = false
  }
}

async function requestReset() {
  if (!resetForm.email) {
    ElMessage.error(text.value.emailRequired)
    return
  }
  resetLoading.value = true
  try {
    await requestPasswordResetApi(resetForm.email)
    ElMessage.success(text.value.resetRequested)
  } catch (err) {
    errorMsg.value = getApiErrorMessage(err, '密码找回请求失败，请稍后重试')
    ElMessage.error(errorMsg.value)
  } finally {
    resetLoading.value = false
  }
}

async function confirmReset() {
  if (!resetForm.token || !resetForm.newPassword) {
    ElMessage.error(text.value.resetInputRequired)
    return
  }
  if (resetForm.newPassword.length < 6) {
    ElMessage.error(text.value.passwordMin)
    return
  }
  resetLoading.value = true
  try {
    await confirmPasswordResetApi({ token: resetForm.token, new_password: resetForm.newPassword })
    ElMessage.success(text.value.resetSuccess)
    forgotOpen.value = false
  } catch (err) {
    errorMsg.value = getApiErrorMessage(err, text.value.resetFailed)
    ElMessage.error(errorMsg.value)
  } finally {
    resetLoading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f2f2f2;
  padding: 12px;
}

.login-wrapper {
  width: 100%;
  max-width: 1100px;
  display: grid;
  align-items: stretch;
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 32px rgba(0, 0, 0, 0.15);
  min-height: 640px;
  grid-template-columns: 1.15fr 1fr;

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
    min-height: auto;
    max-width: 420px;
  }
}

/* ── Left panel ── */
.login-left {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 48px;
  overflow: hidden;

  @media (max-width: 768px) {
    display: none;
  }
}

.silk-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.silk-overlay {
  pointer-events: none;
  position: absolute;
  inset: 0;
  z-index: 1;
  background: linear-gradient(to bottom right, rgba(0, 0, 0, 0.2) 0%, transparent 50%, rgba(0, 0, 0, 0.4) 100%);
}

.brand-text {
  position: relative;
  z-index: 2;
  color: #fff;
  margin-top: auto;

  h2 {
    font-size: 40px;
    font-weight: 600;
    line-height: 1.1;
    letter-spacing: -0.5px;
    margin: 0;
  }

  p {
    margin-top: 16px;
    max-width: 320px;
    font-size: 14px;
    line-height: 1.65;
    color: rgba(255, 255, 255, 0.65);
  }
}

/* ── Right panel ── */
.login-right {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  padding: 24px;

  @media (min-width: 769px) {
    padding: 56px;
  }
}

.form-container {
  width: 100%;
  max-width: 360px;
}

.form-header {
  margin-bottom: 28px;

  h1 {
    font-size: 26px;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.3px;
    color: #171717;
    margin: 0;
  }

  p {
    margin-top: 8px;
    font-size: 14px;
    color: #737373;
  }
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #404040;
}

.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-bottom: 6px;
}

.forgot-link {
  appearance: none;
  border: 0;
  background: transparent;
  box-shadow: none;
  padding: 0;
  color: #737373;
  font: inherit;
  font-size: 14px;
  line-height: 1.25;
  cursor: pointer;
  text-align: right;
  transition: color 0.2s ease, text-decoration-color 0.2s ease;

  &:hover {
    color: #404040;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  &:focus-visible {
    outline: 2px solid #8f8ab0;
    outline-offset: 3px;
    border-radius: 2px;
  }
}

:deep(.el-form-item) {
  margin-bottom: 15px;

  .el-form-item__content {
    flex-direction: column;
    flex-wrap: nowrap;
  }
}

:deep(.el-form-item__content > *) {
  width: 100%;
}

:deep(.el-input) {
  --el-input-bg-color: #f1f1f0;
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: transparent;
  --el-input-placeholder-color: #a3a3a3;

  .el-input__wrapper {
    border-radius: 10px;
    padding-left: 14px;
    padding-right: 14px;
    padding-top: 6px;
    padding-bottom: 6px;
    background: #f1f1f0;
    box-shadow: none;
    transition: background 0.2s, box-shadow 0.2s;

    &:hover {
      background: #ebebea;
    }

    &.is-focus {
      background: #e7e7e6;
      box-shadow: 0 0 0 1px #8F8AB0;
    }
  }

  .el-input__inner {
    color: #171717;
    font-size: 14px;

    &::placeholder {
      color: #a3a3a3;
    }
  }

  .el-input__prefix-inner {
    color: #a3a3a3;
  }
}

.pwd-wrap {
  position: relative;

  .pwd-toggle {
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    z-index: 2;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 0;
    background: transparent;
    color: #a3a3a3;
    cursor: pointer;
    font-size: 16px;
    padding: 0;

    &:hover {
      color: #404040;
    }
  }

  :deep(.el-input .el-input__wrapper) {
    padding-right: 42px;
  }
}

.error-banner {
  border-radius: 10px;
  border: 1px solid #d5d1e6;
  background: #f3f2f8;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 14px;
  color: #8F8AB0;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  border-radius: 10px;
  padding-top: 12px;
  padding-bottom: 12px;
  background: #171717;
  border-color: #171717;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  transition: background 0.2s;

  &:hover:not(:disabled) {
    background: #262626;
    border-color: #262626;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.form-footer {
  margin-top: 28px;
  font-size: 13px;
  color: #a3a3a3;

  a {
    color: #171717;
    margin-left: 4px;
    font-weight: 500;
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}
.login-toast {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9999;
  width: 330px;
  height: 80px;
  border-radius: 8px;
  padding: 10px 15px;
  background: #fff;
  box-shadow: rgba(149,157,165,0.2) 0 8px 24px;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 15px;
}
.login-toast-wave {
  position: absolute;
  transform: rotate(90deg);
  left: -31px;
  top: 32px;
  width: 80px;
  fill: #04e4003a;
}
.login-toast-icon {
  width: 35px; height: 35px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #04e40048;
  border-radius: 50%;
  flex-shrink: 0;
  svg { width: 17px; height: 17px; color: #269b24; }
}
.login-toast-text { flex: 1; }
.login-toast-title { margin: 0; color: #269b24; font-size: 17px; font-weight: 700; }
.login-toast-sub { margin: 0; font-size: 14px; color: #555; }
.login-toast-close { width: 18px; height: 18px; color: #555; cursor: pointer; flex-shrink: 0; }
.toast-fade-enter-active { transition: all 0.3s ease-out; }
.toast-fade-leave-active { transition: all 0.2s ease-in; }
.toast-fade-enter-from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
.toast-fade-leave-to { opacity: 0; transform: translateX(-50%) translateY(-20px); }
</style>
