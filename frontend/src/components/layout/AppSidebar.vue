<template>
  <aside :class="['app-sidebar', { collapsed, 'hover-locked': hoverLocked }]">
    <!-- Header: brand + toggle -->
    <div class="sidebar-header">
      <img src="/favicon.svg" alt="logo" class="brand-logo" />
      <span class="brand-text">钢铁表面缺陷检测</span>
      <button class="toggle-btn" :title="collapsed ? text.expandSidebar : text.collapseSidebar" @click="handleToggle">
        <DockLeft class="toggle-icon" />
      </button>
    </div>

    <!-- Body: navigation + sessions -->
    <div class="sidebar-body">
      <nav class="sidebar-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          :class="['nav-item', { active: activeMenu === item.path }]"
          :title="collapsed ? item.title : ''"
        >
          <el-icon class="nav-icon">
            <component :is="item.icon" />
          </el-icon>
          <span v-show="!collapsed" class="nav-label">{{ item.title }}</span>
          <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
        </router-link>
      </nav>

      <!-- Sessions section (chat history) -->
      <div v-show="!collapsed" class="sidebar-sessions">
        <div class="sessions-header">
          <span>{{ text.chatHistory }}</span>
          <button class="sessions-new-btn" :title="text.newChat" @click="handleNewChat">
            <Plus />
          </button>
        </div>
        <div class="sessions-tools">
          <input
            v-model="sessionQuery"
            class="session-search"
            :placeholder="text.searchSessions"
            @keydown.enter="handleSearchSessions"
          />
          <button class="session-tool-btn" type="button" @click="handleSearchSessions">{{ text.search }}</button>
        </div>
        <div class="sessions-list">
          <div v-if="!agentStore.sessions.length" class="sessions-empty">
            {{ text.noSessions }}
          </div>
          <div
            v-for="session in agentStore.sessions"
            :key="session.id"
            :class="['session-item', { active: session.id === agentStore.currentSessionId && activeMenu === '/chat' }]"
            @click="handleSwitchSession(session.id)"
          >
            <input
              v-if="editingSessionId === session.id"
              v-model="editingTitle"
              class="session-title-input"
              @click.stop
              @keydown.enter.stop.prevent="commitRename(session)"
              @keydown.esc.stop.prevent="cancelRename"
            />
            <span v-else class="session-title">
              <template v-if="userStore.isSuperuser && session.ownerUsername">[{{ session.ownerUsername }}] </template>{{ session.title || text.newChat }}
            </span>
            <div
              v-if="!userStore.isSuperuser || session.ownerId === userStore.user?.id"
              class="session-actions"
            >
              <button class="session-action" :title="text.rename" @click.stop="startRename(session)">✎</button>
              <button class="session-action danger" :title="text.delete" @click.stop="handleDeleteSession(session.id)">
                <Trash />
              </button>
            </div>
          </div>
          <div ref="sessionSentinel" class="sessions-sentinel" aria-hidden="true" />
          <div v-if="agentStore.sessionsLoading" class="sessions-load-state">正在加载会话…</div>
          <div v-else-if="agentStore.sessionTotal > 0 && agentStore.sessions.length >= agentStore.sessionTotal" class="sessions-load-state">没有更多会话</div>
        </div>
      </div>
    </div>

    <!-- Footer: user menu -->
    <div class="sidebar-footer" ref="footerRef">
      <button
        type="button"
        class="user-btn"
        :aria-expanded="menuOpen"
        aria-haspopup="menu"
        @click="menuOpen = !menuOpen"
        @keydown.esc.stop="menuOpen = false"
      >
        <el-avatar :size="24" :src="userStore.avatar || undefined" class="user-avatar">
          {{ userStore.username?.charAt(0)?.toUpperCase() }}
        </el-avatar>
        <span v-show="!collapsed" class="user-name">{{ userStore.username }}</span>
        <ChevronsUpDown v-show="!collapsed" class="user-chevron" />
      </button>
      <Teleport to="body">
        <div v-if="menuOpen" class="user-menu-overlay" @click="menuOpen = false" />
        <transition name="menu-fade">
          <div v-if="menuOpen" class="user-menu-card" :style="menuStyle" role="menu">
            <ul class="user-menu-list">
              <li>
                <button type="button" class="user-menu-item" role="menuitem" @click="handleMenuCommand('settings')">
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
                  <circle r="3" cy="12" cx="12" />
                </svg>
                <span class="user-menu-label">{{ text.settings }}</span>
                </button>
              </li>
            </ul>
            <ul class="user-menu-list">
              <li><button type="button" class="user-menu-item" role="menuitem" @click="handleMenuCommand('help')"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M9.6 9a2.5 2.5 0 1 1 4.1 1.9c-1 .8-1.7 1.2-1.7 2.6" /><path d="M12 17h.01" /></svg><span class="user-menu-label">{{ text.help }}</span></button></li>
            </ul>
            <div class="user-menu-sep" />
            <ul class="user-menu-list">
              <li>
                <button type="button" class="user-menu-item danger" role="menuitem" @click="handleMenuCommand('logout')">
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                  <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                  <line y2="17" y1="11" x2="10" x1="10" /><line y2="17" y1="11" x2="14" x1="14" />
                </svg>
                <span class="user-menu-label">{{ text.logout }}</span>
                </button>
              </li>
            </ul>
          </div>
        </transition>

        <!-- Logout confirm dialog -->
        <div v-if="showLogoutConfirm" class="logout-overlay" @click.self="showLogoutConfirm = false" />
        <transition name="logout-card-fade">
          <div v-if="showLogoutConfirm" class="logout-card" role="alertdialog" aria-modal="true">
            <button class="logout-card-close" @click="showLogoutConfirm = false" :aria-label="text.cancel">
              <svg height="20px" viewBox="0 0 384 512">
                <path d="M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L192 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 150.6z" />
              </svg>
            </button>
            <div class="logout-card-content">
              <p class="logout-card-heading">{{ text.logoutTitle }}</p>
              <p class="logout-card-description">{{ text.logoutMessage }}</p>
            </div>
            <div class="logout-card-actions">
              <button class="logout-btn secondary" @click="showLogoutConfirm = false">{{ text.cancel }}</button>
              <button class="logout-btn primary" @click="handleLogoutConfirm">{{ text.confirm }}</button>
            </div>
          </div>
        </transition>
      </Teleport>
    </div>

    <SettingsModal v-model="settingsVisible" @closed="restoreSettingsFocus" />
  </aside>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import { ChevronsUpDown, MessageCircleDetail, Capture, Computer, History, ChartTrend, Plus, Trash, DockLeft, Shield, ClipboardCheck } from '@boxicons/vue'
import { FolderOpened } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SettingsModal from '@/components/settings/SettingsModal.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})

const emit = defineEmits(['update:collapsed'])

const hoverLocked = ref(false)
const settingsVisible = ref(false)
const settingsReturnTarget = ref(null)
const menuOpen = ref(false)
const showLogoutConfirm = ref(false)
const sessionSearch = ref('')
const footerRef = ref(null)
const sessionQuery = ref('')
const editingSessionId = ref('')
const editingTitle = ref('')
const sessionSentinel = ref(null)
let sessionObserver = null
let hoverLockTimer = null

const menuStyle = computed(() => {
  if (!footerRef.value) return {}
  const rect = footerRef.value.getBoundingClientRect()
  return {
    position: 'fixed',
    left: `${rect.left}px`,
    bottom: `${window.innerHeight - rect.top + 8}px`,
    minWidth: `${Math.max(rect.width, 180)}px`,
  }
})

function handleToggle() {
  emit('update:collapsed', !props.collapsed)
  hoverLocked.value = true
  clearTimeout(hoverLockTimer)
  hoverLockTimer = setTimeout(() => { hoverLocked.value = false }, 300)
}

function handleMenuCommand(command) {
  menuOpen.value = false
  if (command === 'settings') {
    settingsReturnTarget.value = document.activeElement
    settingsVisible.value = true
    return
  }
  if (command === 'help') {
    router.push({ path: '/help', query: { onboarding: '1' } })
    return
  }
  if (command === 'logout') {
    showLogoutConfirm.value = true
    return
  }
}

async function handleLogoutConfirm() {
  showLogoutConfirm.value = false
  agentStore.clearUserScope()
  await userStore.logout()
  await router.replace('/login')
}

function restoreSettingsFocus() {
  nextTick(() => {
    settingsReturnTarget.value?.focus?.()
    settingsReturnTarget.value = null
  })
}

function closeMenuOnClick(e) {
  if (footerRef.value && !footerRef.value.contains(e.target)) {
    menuOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', closeMenuOnClick)
  sessionObserver = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadNextSessionPage()
  }, { root: document.querySelector('.sessions-list'), rootMargin: '120px' })
  nextTick(() => sessionSentinel.value && sessionObserver.observe(sessionSentinel.value))
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenuOnClick)
  sessionObserver?.disconnect()
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const agentStore = useAgentStore()
const settingsStore = useSettingsStore()

onMounted(() => {
  agentStore.fetchSessions(userStore.user?.id).catch(() => {})
})

const activeMenu = computed(() => '/' + route.path.split('/')[1])

const text = computed(() => settingsStore.isEnglish ? {
  expandSidebar: 'Expand sidebar',
  collapseSidebar: 'Collapse sidebar',
  chat: 'Chat',
  detection: 'Detection',
  training: 'Training',
  tasks: 'Task Center',
  files: 'Files',
  history: 'History',
  dashboard: 'Dashboard',
  admin: 'Administration',
  chatHistory: 'Chats',
  newChat: 'New chat',
  noSessions: 'No chats',
  notifications: 'Notifications',
  noNotifications: 'No notifications',
  searchSessions: 'Search chats',
  sessionRestoreFailed: 'Session restore failed.',
  retry: 'Retry',
  previous: 'Previous',
  next: 'Next',
  rename: 'Rename',
  archive: 'Archive',
  delete: 'Delete',
  search: 'Search',
  prev: 'Prev',
  renameFailed: 'Failed to rename chat',
  archiveFailed: 'Failed to archive chat',
  restoreFailed: 'Failed to restore chat',
  settings: 'Settings',
  help: 'Help',
  logout: 'Log out',
  logoutTitle: 'Confirm',
  logoutMessage: 'Are you sure you want to log out?',
  confirm: 'Confirm',
  cancel: 'Cancel',
} : {
  searchSessions: '\u641c\u7d22\u4f1a\u8bdd',
  sessionRestoreFailed: '\u4f1a\u8bdd\u6062\u590d\u5931\u8d25',
  retry: '\u91cd\u8bd5',
  previous: '\u4e0a\u4e00\u9875',
  next: '\u4e0b\u4e00\u9875',
  notifications: '通知中心',
  noNotifications: '暂无通知',
  expandSidebar: '展开侧栏',
  collapseSidebar: '收起侧栏',
  chat: '智能对话',
  detection: '检测工作台',
  training: '模型训练',
  tasks: '任务中心',
  files: '文件查看',
  history: '历史记录',
  dashboard: '数据看板',
  admin: '管理中心',
  chatHistory: '会话历史',
  newChat: '新对话',
  noSessions: '暂无会话',
  delete: '删除',
  rename: '重命名',
  archive: '归档',
  search: '搜索',
  prev: '上一页',
  renameFailed: '会话重命名失败',
  archiveFailed: '会话归档失败',
  restoreFailed: '会话恢复失败',
  settings: '设置',
  help: '帮助',
  logout: '退出登录',
  logoutTitle: '提示',
  logoutMessage: '确定要退出登录吗？',
  confirm: '确定',
  cancel: '取消',
})

const menuItems = computed(() => [
  { path: '/chat', title: text.value.chat, icon: MessageCircleDetail },
  { path: '/detection', title: text.value.detection, icon: Capture },
  { path: '/training', title: text.value.training, icon: Computer },
  { path: '/history', title: text.value.history, icon: History },
  { path: '/files', title: settingsStore.isEnglish ? 'File lifecycle' : '文件生命周期', icon: FolderOpened },
  { path: '/dashboard', title: text.value.dashboard, icon: ChartTrend },
  { path: '/admin', title: text.value.admin, icon: Shield, adminOnly: true },
].filter((item) => !item.adminOnly || userStore.isSuperuser))

function handleNewChat() {
  agentStore.saveSession()
  agentStore.newChat()
  if (route.path !== '/chat') router.push('/chat')
}

async function handleSwitchSession(id) {
  agentStore.saveSession()
  agentStore.loadSession(id).catch((error) => {
    ElMessage.error(error?.response?.data?.detail || error?.message || text.value.restoreFailed)
  })
  if (route.path !== '/chat') router.push('/chat')
}

async function handleDeleteSession(id) {
  try {
    await agentStore.deleteSession(id)
    await agentStore.fetchSessions()
  } catch {
    agentStore.fetchSessions().catch(() => {})
  }
}

function handleSearchSessions() {
  agentStore.sessionSearch = sessionQuery.value.trim()
  agentStore.fetchSessions({ userId: userStore.user?.id, search: agentStore.sessionSearch, page: 1 }).catch(() => {})
}

async function loadNextSessionPage() {
  if (agentStore.sessionsLoading || agentStore.sessionTotal <= agentStore.sessions.length) return
  await agentStore.fetchSessions({ userId: userStore.user?.id, search: agentStore.sessionSearch, page: agentStore.sessionPage + 1, append: true }).catch(() => {})
}

function startRename(session) {
  editingSessionId.value = session.id
  editingTitle.value = session.title || text.value.newChat
}

function cancelRename() {
  editingSessionId.value = ''
  editingTitle.value = ''
}

async function commitRename(session) {
  try {
    await agentStore.renameSession(session.id, editingTitle.value)
    cancelRename()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || text.value.renameFailed)
  }
}

</script>

<style lang="scss" scoped>
.app-sidebar {
  position: sticky;
  top: 0;
  width: $sidebar-width;
  height: 100vh;
  background: var(--app-sidebar-bg);
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;

  &.collapsed {
    width: $sidebar-collapsed-width;
  }
}

.sidebar-notifications { position: relative; padding: 8px 12px 0; }
.notification-trigger {
  width: 100%; border: 1px solid var(--app-border); border-radius: 8px; background: transparent;
  color: var(--app-text); padding: 8px 10px; text-align: left; cursor: pointer;
  display: flex; justify-content: space-between; align-items: center;
}
.notification-panel {
  position: absolute; z-index: 10; left: 12px; right: 12px; top: 48px; max-height: 280px; overflow: auto;
  background: var(--app-surface, #fff); border: 1px solid var(--app-border); border-radius: 10px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, .14); padding: 6px;
}
.notification-item { width: 100%; border: 0; border-radius: 7px; background: transparent; padding: 8px; text-align: left; cursor: pointer; display: flex; flex-direction: column; gap: 3px; }
.notification-item:hover, .notification-item.unread { background: var(--app-muted, #f4f4f5); }
.notification-item-title { font-size: 12px; font-weight: 650; color: var(--app-text); }
.notification-item-message { font-size: 11px; color: var(--app-text-secondary); line-height: 1.35; }

/* ── Header ── */
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 52px;
  padding: 0 16px;
  flex-shrink: 0;
  position: relative;
}

.brand-logo {
  width: 26px; height: 26px;
  flex-shrink: 0;
  transition: opacity 0.15s;
}

.brand-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--app-text);
  white-space: nowrap;
  flex: 1;
  opacity: 1;
}

.toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px; height: 20px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #6e6e6e;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 1;
  transition: opacity 0.12s;
  padding: 0;

  &:hover {
    color: var(--app-text);
    background: var(--app-hover);
  }
}

.toggle-icon {
  width: 20px; height: 20px;
}

/* ── Collapsed state header ── */
.collapsed.hover-locked:hover .brand-logo { opacity: 1; }
.collapsed.hover-locked:hover .toggle-btn { opacity: 0; }

.collapsed .sidebar-header {
  justify-content: flex-start;
  padding: 0 18px;
}

.collapsed .sidebar-header > * {
  position: absolute;
}

.collapsed .brand-text {
  opacity: 0;
  pointer-events: none;
}

.collapsed .brand-logo {
  opacity: 1;
  left: 16px;
}

.collapsed .toggle-btn {
  opacity: 0;
  transition: opacity 0s;
}

.collapsed:hover .brand-logo {
  opacity: 0;
  transition: opacity 0s;
}

.collapsed:hover .toggle-btn {
  opacity: 1;
  transition: opacity 0s 0s;
}

/* ── Body (nav + sessions) ── */
.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  min-height: 0;
}

/* ── Nav ── */
.sidebar-nav {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex-shrink: 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 6px 10px;
  border-radius: 10px;
  color: var(--app-text);
  text-decoration: none;
  font-size: 14px;
  font-weight: 400;
  transition: all 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  position: relative;

  &:hover {
    background: var(--app-hover);
  }

  &.active {
    font-weight: 500;
    background: var(--app-active);

    &::before {
      content: '';
      position: absolute;
      left: 0; top: 50%;
      transform: translateY(-50%);
      width: 3px; height: 18px;
      border-radius: 0 3px 3px 0;
      background: #8F8AB0;
    }
  }
}

.nav-icon {
  font-size: 20px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
}

.nav-label {
  flex: 1;
  min-width: 0;
}

.nav-badge {
  font-size: 11px;
  background: rgba(143,138,176,0.18);
  color: #6b6390;
  min-width: 18px; height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  padding: 0 5px;
  flex-shrink: 0;
}

/* ── Sessions ── */
.sidebar-sessions {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0 8px 8px;
  overflow: hidden;
  white-space: nowrap;
}

.sessions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 10px 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text);
  flex-shrink: 0;
}

.sessions-new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #6e6e6e;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    color: var(--app-text);
    background: var(--app-hover);
  }

  svg {
    width: 16px; height: 16px;
  }
}

.sessions-tools {
  display: flex;
  gap: 6px;
  padding: 0 8px 8px;
}

.session-search {
  min-width: 0;
  flex: 1;
  height: 30px;
  padding: 0 9px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  font: inherit;
  font-size: 12px;
  outline: 0;

  &:focus {
    border-color: #8f8ab0;
  }
}

.session-tool-btn,
.sessions-pager button {
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 12px;
  cursor: pointer;

  &:hover:not(:disabled) {
    background: var(--app-hover);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
}

.sessions-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.sessions-empty {
  padding: 16px 14px;
  font-size: 13px;
  color: #b0b0b0;
  text-align: center;
}
.sessions-load-state { padding: 8px 14px; color: var(--app-text-secondary, #777); font-size: 11px; text-align: center; }

.sessions-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 14px;
  color: var(--app-danger, #b42318);
  font-size: 11px;
}
.sessions-error button {
  border: 0;
  background: transparent;
  color: var(--app-primary, #2563eb);
  cursor: pointer;
  font-size: 11px;
  padding: 0;
}
.sessions-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  color: var(--app-text-secondary, #777);
  font-size: 11px;
}
.sessions-pagination button {
  border: 0;
  background: transparent;
  color: var(--app-primary, #2563eb);
  cursor: pointer;
  font-size: 11px;
  padding: 0;
}
.sessions-pagination button:disabled {
  color: var(--app-text-muted, #aaa);
  cursor: not-allowed;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 6px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--app-text);
  cursor: pointer;
  text-align: left;
  font-size: 14px;
  font-weight: 400;
  transition: all 0.1s ease;
  gap: 6px;

  &:hover {
    background: var(--app-hover);
  }

  &.active {
    background: var(--app-active);
    font-weight: 500;
  }
}

.session-title {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-title-input {
  min-width: 0;
  flex: 1;
  height: 26px;
  padding: 0 6px;
  border: 1px solid #8f8ab0;
  border-radius: 6px;
  background: var(--app-surface);
  color: var(--app-text);
  font: inherit;
  outline: 0;
}

.session-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .session-actions {
  opacity: 1;
}

.session-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px; height: 20px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--app-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
  padding: 0;
  font-size: 12px;

  svg {
    width: 12px; height: 12px;
  }

  &:hover {
    color: var(--app-text);
    background: var(--app-hover);
  }

  &.danger:hover {
    color: #f56c6c;
    background: rgba(245,108,108,0.15);
  }
}

.sessions-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 4px 0;
  color: var(--app-muted);
  font-size: 12px;
}

/* ── Footer ── */
.sidebar-footer {
  padding: 12px 10px;
  flex-shrink: 0;
  border-top: 1px solid var(--app-border);

  :deep(.el-dropdown) {
    display: block;
    width: 100%;
  }
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  font: inherit;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
  overflow: hidden;

  &:hover {
    background: var(--app-hover);
  }
}

.user-avatar {
  flex-shrink: 0;
}

.user-name {
  flex: 1;
  font-size: 16px;
  font-weight: 400;
  color: var(--app-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-chevron {
  width: 16px; height: 16px;
  color: rgba(0,0,0,0.3);
  flex-shrink: 0;
}

</style>

<!-- User menu (teleported to body, unscoped) -->
<style lang="scss">
.user-menu-overlay {
  position: fixed;
  inset: 0;
  z-index: 1999;
}

.user-menu-card {
  z-index: 2000;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
}

.user-menu-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0;
  margin: 0;
}

.user-menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--app-text);
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.25s ease-out;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  font: inherit;

  svg {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    transition: all 0.25s ease-out;
  }

  &:hover {
    background-color: #5353ff;
    color: #ffffff;
    transform: translate(1px, -1px);

    svg {
      stroke: #ffffff;
    }
  }

  &:active {
    transform: scale(0.98);
  }

  &.danger {
    &:hover {
      background-color: #8e2a2a;
      color: #ffffff;

      svg {
        stroke: #ffffff;
      }
    }
  }
}

.user-menu-label {
  font-weight: 400;
}

.user-menu-sep {
  border-top: 1px solid var(--app-border);
  margin: 0;
}

.menu-fade-enter-active {
  transition: all 0.2s ease-out;
}
.menu-fade-leave-active {
  transition: all 0.15s ease-in;
}
.menu-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.menu-fade-leave-to {
  opacity: 0;
  transform: translateY(3px);
}

/* ── Logout confirm card ── */
.logout-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(0, 0, 0, 0.18);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.logout-card {
  position: fixed;
  inset: 0;
  z-index: 3001;
  margin: auto;
  width: 300px;
  height: fit-content;
  background: var(--app-surface);
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 30px;
  box-shadow: 20px 20px 30px rgba(0, 0, 0, 0.068);
}

.logout-card-close {
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background-color: transparent;
  position: absolute;
  top: 20px;
  right: 20px;
  cursor: pointer;
  padding: 0;
}

.logout-card-close svg {
  fill: rgb(175, 175, 175);
}

.logout-card-close:hover svg {
  fill: black;
}

.logout-card-content {
  width: 100%;
  height: fit-content;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.logout-card-heading {
  font-size: 20px;
  font-weight: 700;
  color: var(--app-text);
  margin: 0;
}

.logout-card-description {
  font-weight: 400;
  color: var(--app-muted);
  margin: 0;
  font-size: 14px;
}

.logout-card-actions {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.logout-btn {
  width: 50%;
  height: 35px;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
}

.logout-btn.primary {
  background-color: rgb(255, 114, 109);
  color: white;
}

.logout-btn.primary:hover {
  background-color: rgb(255, 73, 66);
}

.logout-btn.secondary {
  background-color: var(--app-hover);
  color: var(--app-text);
}

.logout-btn.secondary:hover {
  background-color: var(--app-border);
}

.logout-card-fade-enter-active {
  transition: all 0.25s ease-out;
}
.logout-card-fade-leave-active {
  transition: all 0.15s ease-in;
}
.logout-card-fade-enter-from {
  opacity: 0;
  transform: scale(0.9);
}
.logout-card-fade-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
</style>
