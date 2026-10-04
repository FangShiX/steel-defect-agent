<template>
  <div class="files-page">
    <ModulePageHeader
      title="文件生命周期"
      description="统一查看文件元数据、对象存储状态和数据库生命周期；上传成功后同时写入 StoredFile 与 MinIO。"
      :mock="false"
    >
      <el-button :icon="Refresh" :loading="loading" @click="loadFiles">刷新</el-button>
      <el-upload
        :show-file-list="false"
        :auto-upload="false"
        :on-change="handleUpload"
        :disabled="uploading"
      >
        <el-button type="primary" :icon="UploadFilled" :loading="uploading">上传并落库</el-button>
      </el-upload>
    </ModulePageHeader>

    <el-alert v-if="pageError" :title="pageError" type="error" show-icon :closable="false" class="page-alert" />

    <section class="lifecycle-summary">
      <div><strong>{{ files.length }}</strong><span>当前文件</span></div>
      <div><strong>{{ countByStatus('active') }}</strong><span>使用中</span></div>
      <div><strong>{{ countByStatus('archived') }}</strong><span>已归档</span></div>
      <div><strong>{{ countByStatus('cleanup_pending') }}</strong><span>待清理</span></div>
    </section>

    <section class="file-card">
      <el-table v-loading="loading" :data="files" row-key="id" empty-text="暂无已落库文件">
        <el-table-column label="文件名" min-width="220" show-overflow-tooltip>
          <template #default="{ row }"><el-icon><Document /></el-icon> {{ row.originalFilename }}</template>
        </el-table-column>
        <el-table-column prop="resourceType" label="资源类型" width="110" />
        <el-table-column label="大小" width="110" align="right"><template #default="{ row }">{{ formatSize(row.fileSize) }}</template></el-table-column>
        <el-table-column label="生命周期" width="125">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light" round>{{ statusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="objectKey" label="对象键" min-width="260" show-overflow-tooltip />
        <el-table-column label="创建时间" width="180"><template #default="{ row }">{{ formatDate(row.createdAt) }}</template></el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.downloadUrl" link type="primary" :icon="Download" tag="a" :href="row.downloadUrl" target="_blank">下载</el-button>
            <el-button v-if="row.status === 'active'" link type="warning" @click="archive(row)">归档</el-button>
            <el-button v-else-if="row.status === 'archived'" link type="success" @click="restore(row)">恢复</el-button>
            <el-button v-if="row.status !== 'deleted'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Document, Download, Refresh, UploadFilled } from '@element-plus/icons-vue'
import ModulePageHeader from '@/components/common/ModulePageHeader.vue'
import { archiveStoredFileApi, deleteStoredFileApi, getStoredFilesApi, restoreStoredFileApi, uploadStoredFileApi } from '@/api/files'

const files = ref([])
const loading = ref(false)
const uploading = ref(false)
const pageError = ref('')

const statusLabels = { active: '使用中', archived: '已归档', deleted: '已删除', cleanup_pending: '待清理' }
function statusLabel(value) { return statusLabels[value] || value }
function statusType(value) { return ({ active: 'success', archived: 'info', deleted: 'danger', cleanup_pending: 'warning' })[value] || '' }
function countByStatus(value) { return files.value.filter((item) => item.status === value).length }
function formatSize(size) { if (!size) return '0 B'; const units = ['B', 'KB', 'MB', 'GB']; const i = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1); return `${(size / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}` }
function formatDate(value) { return value ? new Date(value).toLocaleString() : '—' }

async function loadFiles() {
  loading.value = true; pageError.value = ''
  try { files.value = await getStoredFilesApi(true) } catch (error) { pageError.value = error?.message || '文件列表加载失败' } finally { loading.value = false }
}
async function handleUpload(uploadFile) {
  if (!uploadFile?.raw) return
  uploading.value = true
  try { await uploadStoredFileApi(uploadFile.raw); ElMessage.success('文件已上传并落库'); await loadFiles() } catch (error) { ElMessage.error(error?.message || '文件落库失败') } finally { uploading.value = false }
}
async function archive(row) { try { await archiveStoredFileApi(row.id); ElMessage.success('文件已归档'); await loadFiles() } catch (error) { ElMessage.error(error?.message || '归档失败') } }
async function restore(row) { try { await restoreStoredFileApi(row.id); ElMessage.success('文件已恢复'); await loadFiles() } catch (error) { ElMessage.error(error?.message || '恢复失败') } }
async function remove(row) { try { await ElMessageBox.confirm(`确认删除“${row.originalFilename}”？对象文件也会进入清理流程。`, '删除文件', { type: 'warning' }); await deleteStoredFileApi(row.id); ElMessage.success('文件已删除'); await loadFiles() } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error?.message || '删除失败') } }
onMounted(loadFiles)
</script>

<style lang="scss" scoped>
.files-page { color: #172033; }
.lifecycle-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.lifecycle-summary > div { padding: 18px 20px; border: 1px solid #e6eaf0; border-radius: 12px; background: #fff; }
.lifecycle-summary strong { display: block; color: #2563eb; font-size: 26px; }
.lifecycle-summary span { color: #667085; font-size: 13px; }
.file-card { padding: 18px; border: 1px solid #e6eaf0; border-radius: 14px; background: #fff; }
.page-alert { margin-bottom: 16px; }
@media (max-width: 800px) {
  .lifecycle-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lifecycle-summary > div { padding: 14px; }
  :deep(.module-header__title) { font-size: 28px; }
  .file-card { padding: 12px; }
}
</style>
