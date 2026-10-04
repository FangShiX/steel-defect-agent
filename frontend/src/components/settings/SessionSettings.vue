<template>
  <section class="session-panel">
    <div class="session-toolbar">
      <p>{{ text.sessionsHelp }}</p>
      <el-button size="small" :loading="loading" @click="load">{{ text.refresh }}</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-for="session in sessions" :key="session.id" class="session-row">
      <div class="session-main">
        <strong>{{ session.current ? text.current : text.otherSession }}</strong>
        <span>{{ session.user_agent || text.unknownDevice }}</span>
        <small>{{ session.ip_address || '-' }} · {{ formatDate(session.created_at) }}</small>
      </div>
      <div class="session-meta">
        <el-tag :type="session.revoked || !session.active ? 'info' : 'success'">{{ session.revoked ? text.revoked : (session.active ? text.active : text.expired) }}</el-tag>
        <el-button v-if="!session.current && !session.revoked && session.active" link type="danger" :loading="revoking === session.id" @click="revoke(session)">{{ text.revoke }}</el-button>
      </div>
    </div>
    <el-empty v-if="!loading && !sessions.length" :description="text.noSessions" />
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useUserStore } from '@/stores/user'

defineProps({ text: { type: Object, required: true } })
const userStore = useUserStore()
const sessions = ref([])
const loading = ref(false)
const revoking = ref('')
const error = ref('')

function formatDate(value) { return value ? new Date(value).toLocaleString() : '-' }
async function load() {
  loading.value = true; error.value = ''
  try { sessions.value = await userStore.listSessions() || [] } catch { error.value = 'Unable to load sessions' } finally { loading.value = false }
}
async function revoke(session) {
  revoking.value = session.id
  try { await userStore.revokeSession(session.id); await load() } catch { error.value = 'Unable to revoke session' } finally { revoking.value = '' }
}
onMounted(load)
</script>

<style scoped>
.session-panel { display: flex; flex-direction: column; gap: 12px; }
.session-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.session-toolbar p { margin: 0; color: var(--settings-muted); font-size: 13px; }
.session-row { display: flex; justify-content: space-between; gap: 16px; padding: 12px; border: 1px solid var(--settings-border); border-radius: 10px; }
.session-main { display: flex; min-width: 0; flex-direction: column; gap: 4px; color: var(--settings-text); }
.session-main span, .session-main small { overflow: hidden; color: var(--settings-muted); text-overflow: ellipsis; white-space: nowrap; }
.session-meta { display: flex; flex-shrink: 0; align-items: center; gap: 8px; }
@media (max-width: 640px) { .session-row { align-items: stretch; flex-direction: column; } .session-meta { justify-content: space-between; } }
</style>
