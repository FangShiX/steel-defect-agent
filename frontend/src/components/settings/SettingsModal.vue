<template>
  <Teleport to="body">
    <Transition name="settings-fade">
      <div
        v-if="modelValue"
        class="settings-overlay"
        @mousedown.self="close"
      >
        <section
          ref="dialogRef"
          class="settings-dialog"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
          @keydown="handleKeydown"
        >
          <button class="settings-close" type="button" :aria-label="text.close" @click="close">
            <el-icon><Close /></el-icon>
          </button>

          <SettingsSidebar v-model="activeTab" :labels="text" />

          <main class="settings-content">
            <h2 :id="titleId">{{ activeTitle }}</h2>
            <GeneralSettings v-if="activeTab === 'general'" :text="text" />
            <AccountSettings v-else-if="activeTab === 'account'" :text="text" />
            <SessionSettings v-else-if="activeTab === 'sessions'" :text="text" />
          </main>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useSettingsStore } from '@/stores/settings'
import SettingsSidebar from './SettingsSidebar.vue'
import GeneralSettings from './GeneralSettings.vue'
import AccountSettings from './AccountSettings.vue'
import SessionSettings from './SessionSettings.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'closed'])

const settingsStore = useSettingsStore()
const dialogRef = ref(null)
const activeTab = ref('general')
const titleId = `settings-title-${Math.random().toString(36).slice(2)}`
let previousOverflow = ''

const zhText = {
  expired: '已过期',
  sessions: '登录会话',
  sessionsHelp: '查看仍有效的登录会话，并撤销不再使用的设备。',
  current: '当前会话',
  otherSession: '其他会话',
  unknownDevice: '未知设备',
  active: '有效',
  revoked: '已撤销',
  revoke: '撤销',
  refresh: '刷新',
  noSessions: '暂无登录会话',
  close: '关闭设置',
  general: '常规',
  account: '账户',
  appearance: '外观',
  appearanceHelp: '选择界面显示模式。',
  system: '跟随系统',
  light: '浅色模式',
  dark: '深色模式',
  language: '语言',
  languageHelp: '切换设置弹窗的界面语言。',
  username: '用户名',
  email: '邮箱',
  password: '修改密码',
  passwordHelp: '更新登录密码，请勿使用与当前密码相同的新密码。',
  changePassword: '修改密码',
  currentPassword: '当前密码',
  newPassword: '新密码',
  confirmPassword: '确认新密码',
  togglePassword: '显示或隐藏密码',
  edit: '编辑',
  save: '保存',
  cancel: '取消',
}

const enText = {
  expired: 'Expired',
  sessions: 'Sessions',
  sessionsHelp: 'Review active sign-ins and revoke devices you no longer use.',
  current: 'Current session',
  otherSession: 'Other session',
  unknownDevice: 'Unknown device',
  active: 'Active',
  revoked: 'Revoked',
  revoke: 'Revoke',
  refresh: 'Refresh',
  noSessions: 'No login sessions',
  close: 'Close settings',
  general: 'General',
  account: 'Account',
  appearance: 'Appearance',
  appearanceHelp: 'Choose how the interface is displayed.',
  system: 'System',
  light: 'Light',
  dark: 'Dark',
  language: 'Language',
  languageHelp: 'Switch the settings interface language.',
  username: 'Username',
  email: 'Email',
  password: 'Change password',
  passwordHelp: 'Update your sign-in password.',
  changePassword: 'Change password',
  currentPassword: 'Current password',
  newPassword: 'New password',
  confirmPassword: 'Confirm new password',
  togglePassword: 'Show or hide password',
  edit: 'Edit',
  save: 'Save',
  cancel: 'Cancel',
}

const text = computed(() => (settingsStore.isEnglish ? enText : zhText))
const activeTitle = computed(() => text.value[activeTab.value] || text.value.account)

watch(() => props.modelValue, async (open) => {
  if (open) {
    activeTab.value = activeTab.value || 'general'
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    dialogRef.value?.focus()
  } else {
    document.body.style.overflow = previousOverflow
    emit('closed')
  }
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow
})

function close() {
  emit('update:modelValue', false)
}

function getFocusableElements() {
  return Array.from(dialogRef.value?.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"]), .el-select',
  ) || []).filter((el) => !el.disabled && el.offsetParent !== null)
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }

  if (event.key !== 'Tab') return
  const focusable = getFocusableElements()
  if (!focusable.length) {
    event.preventDefault()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<style lang="scss" scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 4000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.18);
  backdrop-filter: blur(4px);
}

.settings-dialog {
  position: relative;
  width: 680px;
  max-width: calc(100vw - 32px);
  max-height: 80vh;
  display: flex;
  overflow: hidden;
  border: 1px solid var(--settings-border);
  border-radius: 14px;
  background: var(--settings-bg);
  box-shadow: 0 18px 56px rgba(15, 23, 42, 0.22);
  color: var(--settings-text);
  outline: none;
}

.settings-close {
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 1;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--settings-text);
  cursor: pointer;

  &:hover {
    background: var(--settings-hover);
  }
}

.settings-content {
  flex: 1;
  min-width: 0;
  max-height: 80vh;
  overflow-y: auto;
  padding: 22px 26px 28px;

  h2 {
    margin: 0 0 20px;
    padding-bottom: 18px;
    border-bottom: 1px solid var(--settings-border);
    color: var(--settings-text);
    font-size: 18px;
    font-weight: 650;
    letter-spacing: 0;
  }
}

.settings-fade-enter-active,
.settings-fade-leave-active {
  transition: opacity 0.16s ease;

  .settings-dialog {
    transition: transform 0.16s ease, opacity 0.16s ease;
  }
}

.settings-fade-enter-from,
.settings-fade-leave-to {
  opacity: 0;

  .settings-dialog {
    opacity: 0;
    transform: scale(0.975);
  }
}

@media (max-width: 640px) {
  .settings-dialog {
    flex-direction: column;
    width: 100%;
    max-height: min(80vh, 720px);
  }

  .settings-content {
    max-height: none;
    padding: 18px 18px 24px;
  }
}
</style>
