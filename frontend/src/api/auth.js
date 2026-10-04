/**
 * 认证相关 API 接口
 */
import request from '@/utils/request'

/**
 * 用户注册
 * @param {Object} data - { username, email, password }
 */
export function registerApi(data) {
  return request.post('/auth/register', data)
}

/**
 * 用户登录
 * @param {Object} data - { username, password }
 * @returns {Promise} - { access_token, token_type, user }
 */
export function loginApi(data) {
  return request.post('/auth/login', data)
}

export function refreshTokenApi(refreshToken) {
  return request.post('/auth/refresh', null, { headers: { Authorization: `Bearer ${refreshToken}` } })
}

export function logoutApi() {
  return request.post('/auth/logout')
}

export function listAuthSessionsApi() {
  return request.get('/auth/sessions')
}

export function revokeAuthSessionApi(sessionId) {
  return request.delete(`/auth/sessions/${encodeURIComponent(sessionId)}`)
}

export function requestPasswordResetApi(email) {
  return request.post('/auth/password-reset/request', { email })
}

export function confirmPasswordResetApi(payload) {
  return request.post('/auth/password-reset/confirm', payload)
}

/**
 * 获取当前用户信息（需要 Token）
 */
export function getUserInfoApi() {
  return request.get('/auth/me')
}

/**
 * 更新当前用户资料
 * @param {Object} data - { username?, email?, phone?, avatar? }
 */
export function updateUserProfileApi(data) {
  return request.put('/auth/me', data)
}

/**
 * 修改当前用户密码
 * @param {Object} data - { old_password, new_password }
 */
export function changePasswordApi(data) {
  return request.post('/auth/change-password', data)
}
