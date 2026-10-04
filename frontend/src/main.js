import { createApp } from 'vue'

import '@/assets/styles/global.scss'

import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import pinia from './stores'
import { setupErrorReporting } from '@/utils/errorReporter'
import { useSettingsStore } from '@/stores/settings'
import { useUserStore } from '@/stores/user'

const app = createApp(App)
app.use(pinia)
useSettingsStore().init()
const userStore = useUserStore()
if (userStore.token) {
  try {
    await userStore.fetchUserInfo()
  } catch {
    // Keep the persisted session for transient network/service failures. The
    // request interceptor clears it for an invalid or revoked token.
  }
}
app.use(router)
app.use(ElementPlus)
setupErrorReporting(app)

app.mount('#app')
