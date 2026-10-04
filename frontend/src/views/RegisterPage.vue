<template>
  <div class="register-page">
    <div class="register-wrapper">
      <!-- Left — Silk brand panel (same as Login) -->
      <div class="register-left">
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

      <!-- Right — register form -->
      <div class="register-right">
        <div class="form-container">

          <div class="form-header">
            <h1>创建账号</h1>
            <p>注册后即可使用目标检测智能体平台。</p>
          </div>

          <el-form
            ref="formRef"
            :model="registerForm"
            :rules="registerRules"
            label-width="0"
            @submit.prevent="handleRegister"
          >
            <el-form-item prop="username">
              <label class="field-label">用户名</label>
              <el-input
                v-model="registerForm.username"
                placeholder="输入您的用户名"
                :prefix-icon="User"
                autofocus
                autocomplete="username"
              />
            </el-form-item>

            <el-form-item prop="email">
              <label class="field-label">邮箱</label>
              <el-input
                v-model="registerForm.email"
                placeholder="you@example.com"
                :prefix-icon="Message"
                autocomplete="email"
              />
            </el-form-item>

            <el-form-item prop="password">
              <label class="field-label">密码</label>
              <div class="pwd-wrap">
                <el-input
                  v-model="registerForm.password"
                  :type="showPwd ? 'text' : 'password'"
                  placeholder="至少 6 位"
                  :prefix-icon="Lock"
                  autocomplete="new-password"
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

            <el-form-item prop="confirmPassword">
              <label class="field-label">确认密码</label>
              <div class="pwd-wrap">
                <el-input
                  v-model="registerForm.confirmPassword"
                  :type="showConfirmPwd ? 'text' : 'password'"
                  placeholder="再次输入密码"
                  :prefix-icon="Lock"
                  autocomplete="new-password"
                  @keyup.enter="handleRegister"
                />
                <button
                  type="button"
                  class="pwd-toggle"
                  :aria-label="showConfirmPwd ? '隐藏密码' : '显示密码'"
                  @click="showConfirmPwd = !showConfirmPwd"
                >
                  <el-icon><Hide v-if="showConfirmPwd" /><View v-else /></el-icon>
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
              @click="handleRegister"
            >
              {{ loading ? '注册中…' : '注册' }}
            </el-button>
          </el-form>

          <div class="form-footer">
            <span>已有账号？</span>
            <router-link to="/login">立即登录</router-link>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Message, View, Hide } from '@element-plus/icons-vue'
import { registerApi } from '@/api/auth'
import SilkCanvas from '@/components/SilkCanvas.vue'

const router = useRouter()
const formRef = ref(null)
const loading = ref(false)
const showPwd = ref(false)
const showConfirmPwd = ref(false)
const errorMsg = ref('')

const registerForm = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== registerForm.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度为 3-50 个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

async function handleRegister() {
  errorMsg.value = ''
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await registerApi({
      username: registerForm.username,
      email: registerForm.email,
      password: registerForm.password,
    })

    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (err) {
    const data = err?.response?.data
    errorMsg.value = data?.detail || data?.error || '注册失败，请稍后再试'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.register-page {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f2f2f2;
  padding: 12px;
}

.register-wrapper {
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
.register-left {
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
.register-right {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  padding: 16px;
  overflow-y: auto;

  @media (min-width: 769px) {
    padding: 36px 48px;
  }
}

.form-container {
  width: 100%;
  max-width: 360px;
}

.form-header {
  margin-bottom: 20px;

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
  display: block;
  width: 100%;
  margin-bottom: 0px;
  font-size: 13px;
  font-weight: 600;
  color: #404040;
}

:deep(.el-form-item) {
  margin-bottom: 10px;

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
  margin-top: 4px;
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
  margin-top: 18px;
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
</style>
