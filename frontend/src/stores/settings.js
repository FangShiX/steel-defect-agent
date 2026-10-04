import { defineStore } from 'pinia'

const THEME_KEY = 'ssdd_theme'
const LANGUAGE_KEY = 'ssdd_language'
const MEDIA_QUERY = '(prefers-color-scheme: dark)'

let mediaQuery = null
let mediaListener = null

function getSystemTheme() {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia(MEDIA_QUERY).matches ? 'dark' : 'light'
}

function applyTheme(theme) {
  const resolved = theme === 'system' ? getSystemTheme() : theme
  document.documentElement.dataset.theme = resolved
  document.documentElement.dataset.themePreference = theme
  document.documentElement.style.colorScheme = resolved
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    theme: localStorage.getItem(THEME_KEY) || 'system',
    language: localStorage.getItem(LANGUAGE_KEY) || 'zh-CN',
  }),

  getters: {
    isEnglish: (state) => state.language === 'en-US',
  },

  actions: {
    init() {
      this.applyTheme()
      this.watchSystemTheme()
      document.documentElement.lang = this.language === 'en-US' ? 'en' : 'zh-CN'
    },

    setTheme(theme) {
      this.theme = theme
      localStorage.setItem(THEME_KEY, theme)
      this.applyTheme()
      this.watchSystemTheme()
    },

    applyTheme() {
      applyTheme(this.theme)
    },

    watchSystemTheme() {
      if (typeof window === 'undefined') return
      if (!mediaQuery) mediaQuery = window.matchMedia(MEDIA_QUERY)
      if (mediaListener) mediaQuery.removeEventListener('change', mediaListener)
      mediaListener = () => {
        if (this.theme === 'system') this.applyTheme()
      }
      mediaQuery.addEventListener('change', mediaListener)
    },

    setLanguage(language) {
      this.language = language
      localStorage.setItem(LANGUAGE_KEY, language)
      document.documentElement.lang = language === 'en-US' ? 'en' : 'zh-CN'
    },
  },
})
