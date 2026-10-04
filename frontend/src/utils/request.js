/**
 * Axios 请求封装
 * - 统一 baseURL 配置
 * - 请求拦截器：自动注入 JWT Token
 * - 响应拦截器：统一错误处理、Token 过期处理
 */
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import router from '@/router'
import { reportError } from '@/utils/errorReporter'
import { getApiErrorInfo } from '@/utils/apiError'

// ── 创建 Axios 实例 ──────────────────────────────────
const request = axios.create({
  baseURL: '/api',    // 配合 Vite proxy，实际请求转发到后端
  timeout: 30000,     // 请求超时 30 秒
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── 请求拦截器 ──────────────────────────────────────
request.interceptors.request.use(
  (config) => {
    // 从 Pinia store 获取 Token，自动注入请求头
    const userStore = useUserStore()
    // Preserve explicit credentials for refresh and other token-exchange calls.
    if (userStore.token && !config.headers?.Authorization && !config.headers?.authorization) {
      config.headers.Authorization = `Bearer ${userStore.token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// ── 响应拦截器 ──────────────────────────────────────
request.interceptors.response.use(
  (response) => {
    // 请求成功，直接返回响应数据
    if (response.config?._confirmationRetry) {
      ElMessage.success('Confirmed operation completed')
    }
    return response.data
  },
  async (error) => {
    const { response } = error
    const requestUrl = String(error.config?.url || '')
    const confirmationRequired = response?.status === 428
      && response.data?.detail?.code === 'CONFIRMATION_REQUIRED'
    // Telemetry must never report itself, and a 428 confirmation challenge is
    // an expected part of the UI flow rather than a failed operation.
    if (!requestUrl.includes('/operation-logs/client-error') && !confirmationRequired) {
      reportError(error, {
        type: 'api_error',
        method: error.config?.method,
        url: requestUrl,
        status: response?.status,
        request_id: response?.headers?.['x-request-id'] || response?.data?.request_id,
        task_id: response?.data?.task_id || error.config?.task_id,
        session_id: response?.data?.session_id || error.config?.session_id,
        user_id: response?.data?.user_id,
      })
    }

    if (response) {
      const errorInfo = getApiErrorInfo(error)
      const errorDetail = response.data?.detail
      const structuredMessage = errorInfo.message
      if (response.status === 422) {
        const validationMessage = Array.isArray(errorDetail)
          ? errorDetail[0]?.msg
          : structuredMessage
        ElMessage.error(validationMessage || 'Request validation failed')
        return Promise.reject(error)
      }
      const isPublicAuthRequest = /\/auth\/(login|register|password-reset)/.test(String(error.config?.url || ''))
      if (response.status === 401 && isPublicAuthRequest) {
        ElMessage.error(structuredMessage || 'Invalid username or password')
        return Promise.reject(error)
      }
      if (![401, 428].includes(response.status)) {
        ElMessage.error(structuredMessage || `Request failed (${response.status})`)
        return Promise.reject(error)
      }
      switch (response.status) {
        case 401:
          // Token 过期或无效，清除用户信息并跳转登录页
          ElMessage.error(structuredMessage || '登录已过期，请重新登录')
          const userStore = useUserStore()
          if (userStore.refreshToken && !error.config?._retry && !String(error.config?.url || '').includes('/auth/refresh')) {
            error.config._retry = true
            try {
              await userStore.refreshSession()
              error.config.headers.Authorization = `Bearer ${userStore.token}`
              return request(error.config)
            } catch { /* local logout below */ }
          }
          await userStore.logout({ notifyServer: false })
          router.push('/login')
          break

        case 428: {
          const confirmation = response.data?.detail
          if (confirmation?.code === 'CONFIRMATION_REQUIRED' && confirmation.confirmation_id && !error.config?._confirmationRetry) {
            const impact = confirmation.impact?.scope || '该操作会修改或删除受保护资源'
            try {
              await ElMessageBox.confirm(
                `操作对象：${confirmation.target_type || '-'} ${confirmation.target_id || '-'}\n影响范围：${impact}`,
                '高风险操作确认',
                { type: 'warning', confirmButtonText: '确认执行', cancelButtonText: '取消' },
              )
              // Persist the user's decision before retrying. The backend only
              // consumes a confirmation whose durable status is "confirmed".
              await request.post(`/confirmations/${encodeURIComponent(confirmation.confirmation_id)}/confirm`)
              error.config._confirmationRetry = true
              error.config.headers = error.config.headers || {}
              error.config.headers['X-Confirmation-ID'] = confirmation.confirmation_id
              return request(error.config)
            } catch {
              return Promise.reject(error)
            }
          }
          break
        }

        case 403:
          ElMessage.error(structuredMessage || '没有权限执行此操作')
          break

        case 404:
          ElMessage.error(structuredMessage || '请求的资源不存在')
          break

        case 422:
          // Pydantic 验证错误
          const detail = response.data?.detail
          if (Array.isArray(detail)) {
            ElMessage.error(structuredMessage || detail[0]?.msg || '参数验证失败')
          } else {
            ElMessage.error(structuredMessage || detail || '参数验证失败')
          }
          break

        case 500:
          ElMessage.error(structuredMessage || '服务器内部错误')
          break

        default:
          ElMessage.error(structuredMessage || `请求失败 (${response.status})`)
      }
    } else {
      // 网络错误或请求超时
      ElMessage.error('网络连接异常，请检查后端服务是否启动')
    }

    return Promise.reject(error)
  }
)

export default request
