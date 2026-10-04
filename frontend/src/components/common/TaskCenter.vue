<template>
  <div class="task-center">
    <el-badge :value="unreadCount || undefined" :hidden="!unreadCount" type="danger">
      <el-button class="task-center-trigger" :icon="List" :aria-label="uiText.title" @click="visible = true">{{ uiText.title }}</el-button>
    </el-badge>
    <el-drawer v-model="visible" :title="uiText.title" size="min(440px, 92vw)">
      <div class="toolbar"><span>{{ uiText.summary }}</span><RefreshButton :label="uiText.refresh" :loading="loading" @click="refresh" /></div>
      <PageErrorAlert v-if="error" :message="error" :retry-text="uiText.retry" @retry="refresh" />
      <div v-else class="list" v-loading="loading">
        <section v-if="notifications.length" class="task-group">
          <div class="group-title"><strong>{{ uiText.notice }}</strong><span>{{ notifications.length }}</span><el-button v-if="notificationUnreadCount" link type="primary" size="small" @click="markAllRead">{{ settingsStore.isEnglish ? 'Mark all read' : '一键已读' }}</el-button></div>
          <article v-for="item in notifications" :key="item.id" class="notice-item" :class="{ 'is-unread': !item.read_at }" @click="openNotification(item)"><div class="notice-content"><strong>{{ localizedNotificationTitle(item) }}</strong><span>{{ localizedNotificationMessage(item) }}</span></div><button class="close-button" type="button" :aria-label="settingsStore.isEnglish ? 'Close' : '关闭'" @click.stop="closeNotification(item)">×</button></article>
        </section>
        <section v-for="group in visibleGroups" :key="group.key" class="task-group">
          <div class="group-title"><strong>{{ group.label }}</strong><span>{{ group.items.length }}</span><el-button v-if="['failed', 'completed'].includes(group.key) && group.items.some(isUnread)" link type="primary" size="small" @click="markTaskGroupRead(group.items)">{{ settingsStore.isEnglish ? 'Mark all read' : '一键已读' }}</el-button></div>
          <article v-for="task in group.items" :key="`${task.kind}-${task.id}`" class="item">
            <button class="close-button" type="button" :aria-label="settingsStore.isEnglish ? 'Close' : '关闭'" @click.stop="closeTask(task)">×</button><div class="row"><strong>{{ taskTitle(task) }}</strong><span v-if="isUnread(task)" class="new-label">{{ uiText.newLabel }}</span><StatusTag :status="task.status" :label="statusText(task.status)" size="small" /></div>
            <p>{{ taskSummary(task) }}</p>
            <el-progress :percentage="progress(task.progress)" :status="task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : undefined" :stroke-width="8" />
            <el-alert v-if="task.error_message" :title="failureReason(task.error_message)" type="error" :closable="false" show-icon />
            <div class="actions"><el-button link type="primary" @click="openTask(task)">{{ task.status === 'completed' ? uiText.result : task.status === 'failed' ? uiText.detail : uiText.monitor }}</el-button></div>
          </article>
        </section>
        <el-empty v-if="!allTasks.length && !loading" :description="uiText.empty" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { List } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import StatusTag from '@/components/common/StatusTag.vue'
import PageErrorAlert from '@/components/common/PageErrorAlert.vue'
import RefreshButton from '@/components/common/RefreshButton.vue'
import { useTaskStore } from '@/stores/tasks'
import { useUserStore } from '@/stores/user'
import { useSettingsStore } from '@/stores/settings'
import { listNotificationsApi, markAllNotificationsReadApi, markNotificationReadApi } from '@/api/notifications'

const visible = ref(false)
const router = useRouter()
const userStore = useUserStore()
const settingsStore = useSettingsStore()
const taskStore = useTaskStore()
const { trainingTasks, loadingTrainingTasks, detectionTasks, loadingDetectionTasks } = storeToRefs(taskStore)
const error = ref('')
const notifications = ref([])
const unreadIds = ref(new Set())
const previousStatuses = ref({})
const storageKey = computed(() => `ssdd_task_notifications_${userStore.user?.id || 'anonymous'}`)
const closedNotificationsKey = computed(() => `ssdd_closed_notifications_${userStore.user?.id || 'anonymous'}`)
const closedTasksKey = computed(() => `ssdd_closed_tasks_${userStore.user?.id || 'anonymous'}`)
const notificationDisplayKey = computed(() => `ssdd_visible_notifications_${userStore.user?.id || 'anonymous'}`)
const closedNotificationIds = ref(new Set())
const closedTaskKeys = ref(new Set())
const notificationKnownIds = ref(new Set())
const notificationLatestTimestamp = ref(0)
const notificationsInitialized = ref(false)
const notificationUnreadCount = ref(0)
const uiText = computed(() => settingsStore.isEnglish ? {
  title: 'Task Center', refresh: 'Refresh', retry: 'Retry', summary: 'Running tasks and recent results', notice: 'New notifications', running: 'Running', failed: 'Failed', completed: 'Recently completed', emptyRunning: 'No running tasks', emptyFailed: 'No failed tasks', emptyCompleted: 'No recently completed tasks', empty: 'No tasks', newLabel: 'New', result: 'View result', detail: 'View details', monitor: 'View monitoring', unknown: 'Unknown status', failure: 'Task failed. View details.',
} : {
  title: '任务中心', refresh: '刷新', retry: '重试', summary: '查看运行中的任务和最近结果', notice: '新通知', running: '正在运行', failed: '运行失败', completed: '最近完成', emptyRunning: '暂无运行中的任务', emptyFailed: '暂无失败任务', emptyCompleted: '暂无最近完成任务', empty: '暂无任务', newLabel: '新', result: '查看结果', detail: '查看详情', monitor: '查看监控', unknown: '未知状态', failure: '任务执行失败，请查看详情。',
})
const activeStatuses = ['pending', 'running', 'processing']
const allTaskItems = computed(() => [
  ...trainingTasks.value.map((task) => ({ ...task, kind: 'training' })),
  ...detectionTasks.value.map((task) => ({ ...task, kind: 'detection', progress: task.status === 'completed' ? 100 : (task.progress || 0), error_message: task.errorMessage })),
].filter((task, index, items) => !closedTaskKeys.value.has(allTaskKey(task)) && items.findIndex((candidate) => allTaskKey(candidate) === allTaskKey(task)) === index))
const runningTasks = computed(() => allTaskItems.value.filter((task) => activeStatuses.includes(task.status)))
const failedTasks = computed(() => allTaskItems.value.filter((task) => task.status === 'failed').slice(0, 3))
const taskCompletionTimestamp = (task) => new Date(task.completedAt || task.completed_at || task.updatedAt || task.updated_at || task.createdAt || task.created_at || 0).getTime() || 0
const completedTasks = computed(() => allTaskItems.value.filter((task) => ['completed', 'success', 'finished'].includes(task.status)).sort((a, b) => taskCompletionTimestamp(b) - taskCompletionTimestamp(a)).slice(0, 3))
const allTasks = computed(() => [...runningTasks.value, ...failedTasks.value, ...completedTasks.value])
const groups = computed(() => [
  { key: 'running', label: uiText.value.running, empty: uiText.value.emptyRunning, items: runningTasks.value },
  { key: 'failed', label: uiText.value.failed, empty: uiText.value.emptyFailed, items: failedTasks.value },
  { key: 'completed', label: uiText.value.completed, empty: uiText.value.emptyCompleted, items: completedTasks.value },
])
const visibleGroups = computed(() => groups.value.filter((group) => group.items.length))
const visibleTaskKeys = computed(() => new Set(allTasks.value.map(allTaskKey)))
const unreadCount = computed(() => notificationUnreadCount.value + [...unreadIds.value].filter((key) => visibleTaskKeys.value.has(key)).length)
const loading = computed(() => loadingTrainingTasks.value || loadingDetectionTasks.value)
const progress = (value) => Math.min(100, Math.max(0, Number(value) || 0))
const statusText = (status) => ({ pending: settingsStore.isEnglish ? 'Pending' : '等待中', running: settingsStore.isEnglish ? 'Running' : '运行中', processing: settingsStore.isEnglish ? 'Processing' : '处理中', completed: settingsStore.isEnglish ? 'Completed' : '已完成', failed: settingsStore.isEnglish ? 'Failed' : '失败', cancelled: settingsStore.isEnglish ? 'Cancelled' : '已取消' })[status] || uiText.value.unknown
const typeNames = { single: ['Single image', '单图检测'], batch: ['Batch image', '批量图片检测'], zip: ['ZIP', '压缩包检测'], video: ['Video', '视频检测'], camera: ['Camera', '摄像头检测'] }
const typeName = (value) => typeNames[value]?.[settingsStore.isEnglish ? 0 : 1] || (settingsStore.isEnglish ? 'Detection' : '检测')
const taskTitle = (task) => `${task.kind === 'training' ? (settingsStore.isEnglish ? 'Training' : '训练') : typeName(task.taskType)} #${task.id}`
const taskSummary = (task) => task.kind === 'training' ? `${task.model_name || (settingsStore.isEnglish ? 'Unnamed model' : '未命名模型')} · ${task.dataset_name || task.dataset_path || (settingsStore.isEnglish ? 'Unnamed dataset' : '未命名数据集')}` : `${typeName(task.taskType)} · ${task.sceneName || (settingsStore.isEnglish ? 'Default scene' : '默认场景')}`
const localizedTaskMessage = (message) => {
  const raw = String(message || '')
  if (settingsStore.isEnglish || !raw) return raw
  const detectionCompleted = raw.match(/Detection task\s+(\S+)\s+completed with\s+(\d+)\s+detected objects?\.?/i)
  if (detectionCompleted) return `检测任务 ${detectionCompleted[1]} 已完成，检测到 ${detectionCompleted[2]} 个目标。`
  const trainingCompleted = raw.match(/Training task\s+(\S+)\s+completed\.?/i)
  if (trainingCompleted) return `训练任务 ${trainingCompleted[1]} 已完成。`
  const detectionFailed = raw.match(/Detection task\s+(\S+)\s+failed[:：]?\s*(.*)/i)
  if (detectionFailed) return `检测任务 ${detectionFailed[1]} 失败${detectionFailed[2] ? `：${detectionFailed[2]}` : '。'}`
  return raw
}
const failureReason = (reason) => localizedTaskMessage(reason) || uiText.value.failure
const allTaskKey = (task) => `${task.kind}-${task.id}`
const isUnread = (task) => unreadIds.value.has(allTaskKey(task))
function readNotifications() {
  try { unreadIds.value = new Set(JSON.parse(localStorage.getItem(storageKey.value) || '[]')) } catch { unreadIds.value = new Set() }
  try { closedNotificationIds.value = new Set(JSON.parse(localStorage.getItem(closedNotificationsKey.value) || '[]')) } catch { closedNotificationIds.value = new Set() }
  try { closedTaskKeys.value = new Set(JSON.parse(localStorage.getItem(closedTasksKey.value) || '[]')) } catch { closedTaskKeys.value = new Set() }
}
function saveNotifications() { localStorage.setItem(storageKey.value, JSON.stringify([...unreadIds.value])) }
function saveClosedItems() {
  localStorage.setItem(closedNotificationsKey.value, JSON.stringify([...closedNotificationIds.value]))
  localStorage.setItem(closedTasksKey.value, JSON.stringify([...closedTaskKeys.value]))
}
function saveNotificationDisplay() { localStorage.setItem(notificationDisplayKey.value, JSON.stringify(notifications.value.map((item) => String(item.id)))) }
function observeStatus(items) { if (!items.length) return; const next = { ...previousStatuses.value }; items.forEach((task) => { const key = allTaskKey(task); const oldStatus = next[key]; if (oldStatus && oldStatus !== task.status && ['completed', 'failed'].includes(task.status)) unreadIds.value.add(key); next[key] = task.status }); previousStatuses.value = next; saveNotifications() }
function markRead(task) { unreadIds.value.delete(allTaskKey(task)); saveNotifications() }
function markTaskGroupRead(tasks) { tasks.forEach(markRead) }
async function loadNotifications() {
  const result = await listNotificationsApi({ limit: 100, unread_only: false })
  const items = (result?.items || []).sort((a, b) => new Date(b.created_at || b.createdAt || 0) - new Date(a.created_at || a.createdAt || 0))
  const visibleItems = items.filter((item) => !closedNotificationIds.value.has(String(item.id)))
  notificationUnreadCount.value = Number(result?.unread_count ?? items.filter((item) => !item.read_at).length)
  const timestamps = items.map((item) => new Date(item.created_at || item.createdAt || 0).getTime()).filter(Number.isFinite)
  if (!notificationsInitialized.value) {
    let storedIds = []
    try { storedIds = JSON.parse(localStorage.getItem(notificationDisplayKey.value) || '[]') } catch { storedIds = [] }
    notifications.value = storedIds.length
      ? visibleItems.filter((item) => storedIds.includes(String(item.id))).slice(0, 3)
      : visibleItems.slice(0, 3)
    notificationsInitialized.value = true
  } else {
    const newItems = visibleItems.filter((item) => !notificationKnownIds.value.has(String(item.id)) && new Date(item.created_at || item.createdAt || 0).getTime() >= notificationLatestTimestamp.value)
    const refreshedCurrent = notifications.value.map((item) => visibleItems.find((candidate) => String(candidate.id) === String(item.id)) || item).filter((item) => !closedNotificationIds.value.has(String(item.id)))
    notifications.value = [...newItems, ...refreshedCurrent].filter((item, index, list) => list.findIndex((candidate) => String(candidate.id) === String(item.id)) === index).sort((a, b) => new Date(b.created_at || b.createdAt || 0) - new Date(a.created_at || a.createdAt || 0)).slice(0, 3)
  }
  saveNotificationDisplay()
  items.forEach((item) => notificationKnownIds.value.add(String(item.id)))
  if (timestamps.length) notificationLatestTimestamp.value = Math.max(notificationLatestTimestamp.value, ...timestamps)
}
async function refresh() { error.value = ''; try { await Promise.all([taskStore.fetchTrainingTasks(), taskStore.fetchDetectionTasks(), loadNotifications()]) } catch (err) { error.value = err?.response?.data?.detail || err?.message || (settingsStore.isEnglish ? 'Task center failed to load' : '任务中心加载失败') } }
const notificationTitle = (item) => { const raw = String(item.title || ''); if (/fail|error/i.test(raw)) return settingsStore.isEnglish ? 'Task failed' : '任务执行失败'; if (/success|complete|done/i.test(raw)) return settingsStore.isEnglish ? 'Task completed' : '任务已完成'; return raw || (settingsStore.isEnglish ? 'Task status updated' : '任务状态更新') }
const notificationMessage = (item) => { const raw = String(item.message || item.error_message || ''); return /fail|error/i.test(raw) && !settingsStore.isEnglish ? `失败原因：${raw}` : raw || (settingsStore.isEnglish ? 'Task status updated' : '任务状态已更新') }
const localizedNotificationType = (item) => typeName(item.task_type || item.taskType || item.resource_type?.replace('_task', ''))
const localizedNotificationTitle = (item) => {
  const raw = String(item.title || item.message || '')
  const failed = /fail|error|失败|错误/i.test(raw) || item.status === 'failed'
  const completed = /success|complete|done|完成|成功/i.test(raw) || ['completed', 'success'].includes(item.status)
  const id = item.task_id || item.resource_id
  if (settingsStore.isEnglish) return `${localizedNotificationType(item)} ${failed ? 'failed' : completed ? 'completed' : 'updated'}${id ? ` #${id}` : ''}`
  return `${localizedNotificationType(item)}${failed ? '失败' : completed ? '已完成' : '状态更新'}${id ? ` #${id}` : ''}`
}
const localizedNotificationMessage = (item) => {
  const raw = String(item.error_message || item.errorMessage || item.message || '')
  if (settingsStore.isEnglish) return raw || 'Task status updated.'
  const translated = localizedTaskMessage(raw)
  return translated !== raw ? translated : /fail|error/i.test(raw) ? `失败原因：${raw}` : raw || '任务状态已更新。'
}
function closeNotification(item) {
  closedNotificationIds.value.add(String(item.id))
  notifications.value = notifications.value.filter((notice) => String(notice.id) !== String(item.id))
  saveClosedItems()
  saveNotificationDisplay()
}
function closeTask(task) {
  closedTaskKeys.value.add(allTaskKey(task))
  saveClosedItems()
}
async function markAllRead() {
  if (!notificationUnreadCount.value) return
  await markAllNotificationsReadApi()
  notifications.value = notifications.value.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() }))
  notificationUnreadCount.value = 0
  saveNotificationDisplay()
}
async function openNotification(item) { await markNotificationReadApi(item.id); if (!item.read_at) notificationUnreadCount.value = Math.max(0, notificationUnreadCount.value - 1); notifications.value = notifications.value.filter((notice) => notice.id !== item.id); saveNotificationDisplay(); if (item.resource_type === 'training_task') await router.push({ path: '/training', query: { task: item.task_id || item.resource_id } }); else if (item.resource_type === 'detection_task') await router.push({ path: '/history', query: { task: item.task_id || item.resource_id } }) }
async function openTask(task) { markRead(task); visible.value = false; if (task.kind === 'training') { taskStore.selectTrainingTask(task.id); await router.push('/training'); return } await router.push(task.taskType === 'video' ? { path: '/detection', query: { videoTask: task.id } } : { path: '/history', query: { task: task.id } }) }
readNotifications()
watch(allTaskItems, observeStatus, { immediate: true })
let timer = null
onMounted(async () => { await refresh(); timer = window.setInterval(refresh, 5000) })
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<style lang="scss" scoped>
.task-center { position: fixed; z-index: 20; right: 28px; bottom: 28px; }
.task-center-trigger { border-radius: 999px; }
.toolbar, .row, .actions, .group-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.toolbar { margin-bottom: 14px; color: $text-secondary; font-size: 13px; }
.list, .task-group { display: grid; gap: 12px; min-height: 40px; }
.group-title { color: var(--app-text); font-size: 14px; }
.group-title span { color: var(--app-text-secondary); font-size: 12px; }
.item, .notice-item { position: relative; padding: 12px; border: 1px solid var(--app-border); border-radius: $border-radius-md; background: var(--app-surface); }
.notice-item { display: flex; gap: 3px; width: 100%; text-align: left; cursor: pointer; }
.notice-content { display: flex; flex: 1; flex-direction: column; gap: 3px; padding-right: 20px; }
.notice-item.is-unread { border-color: var(--el-color-primary-light-5); }
.close-button { position: absolute; top: 7px; right: 8px; width: 22px; height: 22px; padding: 0; border: 0; color: var(--el-color-danger); background: transparent; font-size: 20px; line-height: 20px; cursor: pointer; }
.close-button:hover { color: var(--el-color-danger-dark-2); }
.item .row, .item .actions { padding-right: 28px; }
.notice-item span, .item p { color: $text-secondary; font-size: 13px; }
.item p { margin: 5px 0 10px; }
.item .el-alert { margin-top: 10px; }
.new-label { color: var(--el-color-danger); font-size: 12px; margin-left: auto; }
</style>
