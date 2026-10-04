/**
 * 鐢ㄦ埛鐘舵€佺鐞?
 * 绠＄悊鐢ㄦ埛鐧诲綍淇℃伅銆乀oken銆佽鑹茬瓑
 */
import { defineStore } from 'pinia'
import { loginApi, getUserInfoApi, updateUserProfileApi, changePasswordApi, refreshTokenApi, logoutApi, listAuthSessionsApi, revokeAuthSessionApi } from '@/api/auth'

const TOKEN_KEY = 'ssdd_token'
const USER_KEY = 'ssdd_user'
const REFRESH_TOKEN_KEY = 'ssdd_refresh_token'

export const useUserStore = defineStore('user', {
  state: () => ({
    // JWT Token
    token: localStorage.getItem(TOKEN_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY) || '',
    // 鐢ㄦ埛淇℃伅
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  }),

  getters: {
    /** 鏄惁宸茬櫥褰?*/
    isLoggedIn: (state) => !!state.token,

    /** 鐢ㄦ埛鍚?*/
    username: (state) => state.user?.username || '',

    /** 鐢ㄦ埛澶村儚 */
    avatar: (state) => state.user?.avatar || '',

    /** 鐢ㄦ埛瑙掕壊鍒楄〃 */
    roles: (state) => state.user?.roles || [],

    /** 鏄惁涓虹鐞嗗憳 */
    isSuperuser: (state) => state.user?.is_superuser || false,
  },

  actions: {
    /**
     * 鐢ㄦ埛鐧诲綍
     * @param {Object} credentials - { username, password }
     */
    async login(credentials) {
      const res = await loginApi(credentials)

      // 淇濆瓨 Token
      this.token = res.access_token
      localStorage.setItem(TOKEN_KEY, res.access_token)
      this.refreshToken = res.refresh_token || ''
      if (this.refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, this.refreshToken)

      // 淇濆瓨鐢ㄦ埛淇℃伅
      this.user = res.user
      localStorage.setItem(USER_KEY, JSON.stringify(res.user))

      return res
    },

    /**
     * 鑾峰彇鏈€鏂扮敤鎴蜂俊鎭?
     */
    async fetchUserInfo() {
      try {
        const user = await getUserInfoApi()
        this.user = user
        localStorage.setItem(USER_KEY, JSON.stringify(user))
        return user
      } catch (error) {
        const status = error?.response?.status
        if ([401, 403].includes(status)) {
          await this.logout({ notifyServer: false })
        }
        throw error
      }
    },

    async updateProfile(payload) {
      const user = await updateUserProfileApi(payload)
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
      return user
    },

    async changePassword(payload) {
      return changePasswordApi(payload)
    },

    async refreshSession() {
      if (!this.refreshToken) throw new Error('No refresh token')
      const res = await refreshTokenApi(this.refreshToken)
      this.token = res.access_token
      this.refreshToken = res.refresh_token || this.refreshToken
      localStorage.setItem(TOKEN_KEY, this.token)
      localStorage.setItem(REFRESH_TOKEN_KEY, this.refreshToken)
      if (res.user) {
        this.user = res.user
        localStorage.setItem(USER_KEY, JSON.stringify(res.user))
      }
      return res
    },

    async listSessions() {
      return listAuthSessionsApi()
    },

    async revokeSession(sessionId) {
      return revokeAuthSessionApi(sessionId)
    },

    /**
     * 閫€鍑虹櫥褰?
     */
    async logout(options = {}) {
      if (options.notifyServer !== false && this.token) {
        try { await logoutApi() } catch { /* local cleanup still makes logout deterministic */ }
      }
      this.token = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
