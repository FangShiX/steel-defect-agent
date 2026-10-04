<template>
  <div :class="['file-browser-page', { 'dataset-bulk-active': datasetBulkMode, 'model-bulk-active': modelBulkMode }]">
    <ModulePageHeader v-if="!embedded" :title="text.title">
      <el-upload :auto-upload="false" :show-file-list="false" accept=".zip" :on-change="uploadDataset"><el-button>{{ text.uploadDataset }}</el-button></el-upload>
      <el-button @click="modelUploadVisible = true">{{ text.uploadModel }}</el-button>
      <RefreshButton :label="text.refresh" :loading="loading" @click="loadAssets" />
    </ModulePageHeader>
    <PageErrorAlert v-if="pageError" :message="pageError" :retry-text="text.refresh" @retry="loadAssets" />
    <el-card shadow="never" class="asset-card dataset-card">
      <template #header><div class="asset-card-header"><div class="card-title">{{ text.datasets }}</div><div class="resource-tools"><el-upload v-if="embedded" :auto-upload="false" :show-file-list="false" accept=".zip" :on-change="uploadDataset"><el-button text size="small" :loading="uploadingDataset">{{ text.uploadDataset }}</el-button></el-upload><el-button text size="small" @click="datasetExpanded = !datasetExpanded">{{ datasetExpanded ? text.collapse : text.expand }}</el-button><el-button text size="small" @click="datasetSearchOpen = !datasetSearchOpen">{{ text.search }}</el-button><el-button text size="small" @click="datasetBulkMode = !datasetBulkMode">{{ text.bulk }}</el-button></div></div></template>
      <div v-if="datasetExpanded && datasetBulkMode" class="resource-bulk-actions"><el-button size="small" :disabled="!selectedDatasets.length" :loading="bulkBusy" @click="bulkDownloadDatasets">{{ text.downloadSelected }}</el-button><el-button type="danger" plain size="small" :disabled="!selectedDatasets.length" :loading="bulkBusy" @click="bulkDeleteDatasets">{{ text.deleteSelected }}</el-button></div>
      <div v-if="datasetExpanded">
      <el-input v-if="datasetSearchOpen" v-model="datasetQuery" class="resource-search" clearable :placeholder="text.searchDataset" />
      <el-table :data="filteredDatasets" v-loading="loading" stripe @selection-change="selectedDatasets = $event">
        <el-table-column v-if="datasetBulkMode" type="selection" width="48" />
        <el-table-column prop="name" :label="text.name" min-width="180" /><el-table-column label="" width="38"><template #default="{ row }"><button class="inline-rename" type="button" title="重命名" @click="openDatasetEditor(row)">✎</button></template></el-table-column><el-table-column prop="path" :label="text.path" min-width="220" />
        <el-table-column :label="text.status" width="120"><template #default="{ row }"><el-tag :type="row.status === 'archived' ? 'info' : (row.ready ? 'success' : 'warning')">{{ row.status === 'archived' ? text.archived : (row.ready ? text.ready : text.incomplete) }}</el-tag></template></el-table-column>
        <el-table-column :label="text.actions" width="210"><template #default="{ row }"><el-button link type="primary" @click="downloadDataset(row)">{{ text.download }}</el-button><el-button v-if="canDelete(row)" link type="primary" @click="openDatasetEditor(row)">{{ text.edit }}</el-button><el-button v-if="canDelete(row)" link type="danger" @click="deleteDataset(row)">{{ text.delete }}</el-button></template></el-table-column>
      </el-table>
      <div v-if="bulkBusy || bulkFailedItems.length" class="bulk-progress" aria-live="polite">
        {{ bulkCompleted }}/{{ bulkTotal }} · {{ settingsStore.isEnglish ? 'success' : '成功' }} {{ bulkSucceeded }} · {{ settingsStore.isEnglish ? 'failed' : '失败' }} {{ bulkFailedItems.length }}
        <ul v-if="bulkFailedItems.length" class="bulk-failures"><li v-for="failure in bulkFailedItems" :key="failure.key">{{ failure.label }}: {{ failure.reason }}</li></ul>
      </div>
      <el-empty v-if="!loading && !datasets.length" :description="text.noDatasets" />
      </div>
    </el-card>
    <el-card shadow="never" class="asset-card model-card">
      <template #header><div class="asset-card-header"><div class="card-title">{{ text.models }}</div><div class="resource-tools"><el-button v-if="embedded" text size="small" type="primary" @click="modelUploadVisible = true">{{ text.uploadModel }}</el-button><el-button text size="small" @click="modelExpanded = !modelExpanded">{{ modelExpanded ? text.collapse : text.expand }}</el-button><el-button text size="small" @click="modelSearchOpen = !modelSearchOpen">{{ text.search }}</el-button><el-button text size="small" @click="modelBulkMode = !modelBulkMode">{{ text.bulk }}</el-button></div></div></template>
      <div v-if="modelExpanded && modelBulkMode" class="resource-bulk-actions"><el-button size="small" :disabled="!selectedModels.length" :loading="bulkBusy" @click="bulkDownloadModels">{{ text.downloadSelected }}</el-button><el-button type="danger" plain size="small" :disabled="!selectedModels.length" :loading="bulkBusy" @click="bulkDeleteModels">{{ text.deleteSelected }}</el-button></div>
      <div v-if="modelExpanded">
      <el-input v-if="modelSearchOpen" v-model="modelQuery" class="resource-search" clearable :placeholder="text.searchModel" />
      <el-table :data="filteredModels" v-loading="loading" stripe @selection-change="selectedModels = $event">
        <el-table-column v-if="modelBulkMode" type="selection" width="48" />
        <el-table-column prop="sceneName" :label="text.scene" min-width="150" /><el-table-column prop="version" :label="text.version" width="120" /><el-table-column prop="modelName" :label="text.model" min-width="220" show-overflow-tooltip /><el-table-column label="" width="38"><template #default="{ row }"><button class="inline-rename" type="button" title="重命名" @click="bulkRenameModels([row])">✎</button></template></el-table-column>
        <el-table-column :label="text.map50" width="110"><template #default="{ row }">{{ formatPercent(row.map50) }}</template></el-table-column><el-table-column :label="text.status" width="180"><template #default="{ row }"><StatusTag :status="row.cleanupPending ? 'failed' : (row.isDefault ? 'completed' : row.status)" :label="modelStatusLabel(row)" /><el-tooltip v-if="row.cleanupPending && row.cleanupError" :content="row.cleanupError"><el-icon class="cleanup-warning"><WarningFilled /></el-icon></el-tooltip></template></el-table-column>
        <el-table-column :label="text.createdAt" min-width="180"><template #default="{ row }">{{ formatDate(row.createdAt) }}</template></el-table-column>
        <el-table-column :label="text.actions" width="260"><template #default="{ row }"><el-button v-if="!row.cleanupPending" link type="primary" @click="downloadModel(row)">{{ text.download }}</el-button><el-button v-if="row.status !== 'deleted' && !row.isDefault && !row.cleanupPending" link type="primary" @click="setDefaultModel(row)">{{ text.setDefault }}</el-button><el-button v-if="row.cleanupPending && canDelete(row)" link type="warning" @click="retryModelCleanup(row)">{{ settingsStore.isEnglish ? 'Retry cleanup' : '重试清理' }}</el-button><el-button v-if="row.status !== 'deleted' && !row.isDefault && canDelete(row)" link type="danger" @click="deleteModel(row)">{{ text.delete }}</el-button></template></el-table-column>
      </el-table>
      <div v-if="bulkBusy || bulkFailedItems.length" class="bulk-progress" aria-live="polite">
        {{ bulkCompleted }}/{{ bulkTotal }} · {{ settingsStore.isEnglish ? 'success' : '成功' }} {{ bulkSucceeded }} · {{ settingsStore.isEnglish ? 'failed' : '失败' }} {{ bulkFailedItems.length }}
        <ul v-if="bulkFailedItems.length" class="bulk-failures"><li v-for="failure in bulkFailedItems" :key="failure.key">{{ failure.label }}: {{ failure.reason }}</li></ul>
      </div>
      <el-empty v-if="!loading && !models.length" :description="text.noModels" />
      </div>
    </el-card>
    <el-dialog v-model="modelUploadVisible" :title="text.uploadModel" width="480px"><el-form :model="modelUpload" label-position="top"><el-form-item :label="text.scene"><el-select v-model="modelUpload.sceneId" class="full-width"><el-option v-for="scene in scenes" :key="scene.id" :label="scene.displayName" :value="scene.id" /></el-select></el-form-item><el-form-item :label="text.version"><el-input v-model="modelUpload.version" /></el-form-item><el-form-item :label="text.model"><el-input v-model="modelUpload.modelName" /></el-form-item><el-form-item label=".pt"><el-upload :auto-upload="false" :limit="1" accept=".pt" :on-change="selectModelFile"><el-button>{{ text.selectFile }}</el-button></el-upload></el-form-item></el-form><template #footer><el-button @click="modelUploadVisible = false">{{ text.cancel }}</el-button><el-button type="primary" :loading="uploading" @click="uploadModel">{{ text.upload }}</el-button></template></el-dialog>
    <el-dialog v-model="datasetEditorVisible" :title="text.editDataset" width="min(480px, 92vw)"><el-form :model="datasetEditor" label-position="top"><el-form-item :label="text.name"><el-input v-model="datasetEditor.displayName" maxlength="200" show-word-limit /></el-form-item><el-form-item :label="text.metadataDescription"><el-input v-model="datasetEditor.description" type="textarea" :rows="4" maxlength="2000" show-word-limit /></el-form-item></el-form><template #footer><el-button @click="datasetEditorVisible = false">{{ text.cancel }}</el-button><el-button type="primary" :loading="savingDatasetMetadata" @click="saveDatasetMetadata">{{ text.save }}</el-button></template></el-dialog>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, WarningFilled } from '@element-plus/icons-vue'
import ModulePageHeader from '@/components/common/ModulePageHeader.vue'
import PageErrorAlert from '@/components/common/PageErrorAlert.vue'
import RefreshButton from '@/components/common/RefreshButton.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { deleteTrainingDataset, downloadTrainingDataset, getTrainingDatasets, updateTrainingDatasetMetadata, uploadTrainingDataset } from '@/api/training'
import { deleteModelVersionApi, downloadModelVersionApi, getModelsApi, getScenesApi, retryModelCleanupApi, setDefaultModelApi, updateModelVersionApi, uploadModelVersionApi } from '@/api/models'
import { getApiErrorMessage } from '@/utils/apiError'
import { useSettingsStore } from '@/stores/settings'
import { useUserStore } from '@/stores/user'
const props = defineProps({ embedded: { type: Boolean, default: false } })
const embedded = computed(() => props.embedded)
const datasetQuery = ref('')
const modelQuery = ref('')
const datasetSearchOpen = ref(false)
const modelSearchOpen = ref(false)
const datasetBulkMode = ref(false)
const modelBulkMode = ref(false)
const datasetExpanded = ref(true)
const modelExpanded = ref(true)
const settingsStore = useSettingsStore(); const userStore = useUserStore(); const loading = ref(false); const uploading = ref(false); const uploadingDataset = ref(false); const bulkBusy = ref(false); const pageError = ref(''); const datasets = ref([]); const models = ref([]); const selectedDatasets = ref([]); const selectedModels = ref([]); const scenes = ref([]); const modelUploadVisible = ref(false); const modelUpload = ref({ sceneId: '', version: '', modelName: '', file: null }); const datasetEditorVisible = ref(false); const savingDatasetMetadata = ref(false); const datasetEditor = ref({ path: '', displayName: '', description: '' })
const text = computed(() => settingsStore.isEnglish ? { title:'Files', refresh:'Refresh', datasets:'Datasets', models:'Model versions', name:'Name', path:'Path', status:'Status', ready:'Ready', incomplete:'Incomplete', archived:'Archived', noDatasets:'No training datasets are available', noModels:'No model versions are available', scene:'Scene', version:'Version', model:'Model', map50:'mAP@50', default:'Default', createdAt:'Created at', actions:'Actions', setDefault:'Set default', download:'Download', edit:'Edit', editDataset:'Edit dataset metadata', metadataDescription:'Description', save:'Save', delete:'Delete', deleteConfirm:'Delete this item?', deleteTitle:'Confirm deletion', deleted:'Deleted', loadFailed:'Failed to load files', actionFailed:'File operation failed', uploadDataset:'Upload dataset', uploadModel:'Upload model', upload:'Upload', selectFile:'Select file', cancel:'Cancel', collapse:'Collapse', expand:'Expand', search:'Search', bulk:'Bulk operations', downloadSelected:'Download selected', deleteSelected:'Delete selected', searchDataset:'Search dataset name or path', searchModel:'Search scene, version, or model name' } : { title:'文件查看', refresh:'刷新', datasets:'数据集', models:'模型版本', name:'名称', path:'路径', status:'状态', ready:'可用', incomplete:'未完成', archived:'已归档', noDatasets:'暂无训练数据集', noModels:'暂无模型版本', scene:'场景', version:'版本', model:'模型', map50:'mAP@50', default:'默认模型', createdAt:'创建时间', actions:'操作', setDefault:'设为默认', download:'下载', edit:'编辑', editDataset:'编辑数据集元数据', metadataDescription:'描述', save:'保存', delete:'删除', deleteConfirm:'确定删除此项吗？', deleteTitle:'确认删除', deleted:'已删除', loadFailed:'文件列表加载失败', actionFailed:'文件操作失败', uploadDataset:'上传数据集', uploadModel:'上传模型', upload:'上传', selectFile:'选择文件', cancel:'取消', collapse:'收起', expand:'展开', search:'搜索', bulk:'批量操作', downloadSelected:'下载所选', deleteSelected:'删除所选', searchDataset:'搜索数据集名称或路径', searchModel:'搜索场景、版本或模型名称' })
const bulkCompleted = ref(0)
const bulkTotal = ref(0)
const bulkSucceeded = ref(0)
const bulkFailedItems = ref([])
const canDelete = (asset) => !asset.isBuiltin && (userStore.isSuperuser || Number(asset.ownerId ?? asset.owner_id) === Number(userStore.user?.id))
function clearBulkFeedback() {
  bulkCompleted.value = 0
  bulkTotal.value = 0
  bulkSucceeded.value = 0
  bulkFailedItems.value = []
}
const modelStatusLabel = (model) => model.cleanupPending ? (settingsStore.isEnglish ? 'Cleanup pending' : '待清理重试') : (model.isDefault ? text.value.default : model.status)
const filteredDatasets = computed(() => {
  const query = datasetQuery.value.trim().toLowerCase()
  if (!query) return datasets.value
  return datasets.value.filter((item) => `${item.name || ''} ${item.path || ''}`.toLowerCase().includes(query))
})
const filteredModels = computed(() => {
  const query = modelQuery.value.trim().toLowerCase()
  if (!query) return models.value
  return models.value.filter((item) => `${item.sceneName || ''} ${item.version || ''} ${item.modelName || ''}`.toLowerCase().includes(query))
})
const formatPercent = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(2)}%` : '-'
const formatDate = (value) => !value ? '-' : new Date(value).toLocaleString(settingsStore.isEnglish ? 'en-US' : 'zh-CN', { hour12:false })
function saveBlob(blob, filename) { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url) }
async function loadAssets() { loading.value=true; pageError.value=''; try { const [data, sceneItems] = await Promise.all([getTrainingDatasets(), getScenesApi()]); datasets.value=data?.items ?? data ?? []; scenes.value=sceneItems; models.value=(await Promise.all(sceneItems.map(async scene => (await getModelsApi(scene.id)).map(model => ({...model, sceneId:scene.id, sceneName:scene.displayName || scene.name}))))).flat() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.loadFailed) } finally { loading.value=false } }
async function setDefaultModel(model) { clearBulkFeedback(); try { await setDefaultModelApi(model.sceneId,model.id); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
async function downloadDataset(row) { try { saveBlob(await downloadTrainingDataset(row.path),`${row.name}.zip`) } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
function openDatasetEditor(row) { datasetEditor.value = { path: row.path, displayName: row.display_name || row.displayName || row.name, description: row.description || '' }; datasetEditorVisible.value = true }
async function saveDatasetMetadata() {
  savingDatasetMetadata.value = true
  try {
    await updateTrainingDatasetMetadata(datasetEditor.value.path, {
      display_name: datasetEditor.value.displayName,
      description: datasetEditor.value.description,
    })
    datasetEditorVisible.value = false
    ElMessage.success(text.value.save)
    await loadAssets()
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.actionFailed)
  } finally {
    savingDatasetMetadata.value = false
  }
}
async function downloadModel(row) { try { saveBlob(await downloadModelVersionApi(row.sceneId,row.id),row.modelName || `${row.version}.pt`) } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
async function confirmDeletion() { try { await ElMessageBox.confirm(text.value.deleteConfirm,text.value.deleteTitle,{type:'warning'}); return true } catch { return false } }
async function deleteDataset(row) { if(await confirmDeletion()) try { await deleteTrainingDataset(row.path); ElMessage.success(text.value.deleted); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
async function deleteModel(row) { if(await confirmDeletion()) try { await deleteModelVersionApi(row.sceneId,row.id); ElMessage.success(text.value.deleted); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
async function runBulk(items, action) {
  if (!items.length) return
  bulkBusy.value = true
  bulkCompleted.value = 0
  bulkTotal.value = items.length
  bulkSucceeded.value = 0
  bulkFailedItems.value = []
  const failures = []
  try {
    for (const item of items) {
      try {
        await action(item)
        bulkSucceeded.value += 1
      } catch (error) {
        const label = item.name || item.modelName || item.version || item.path || '-'
        const reason = getApiErrorMessage(error, text.value.actionFailed)
        failures.push({ key: `${label}-${bulkCompleted.value}`, label, reason })
        bulkFailedItems.value = failures
      }
      finally { bulkCompleted.value += 1 }
    }
    await loadAssets()
    if (failures.length) ElMessage.warning(`${bulkSucceeded.value} ${settingsStore.isEnglish ? 'succeeded' : '项成功'}, ${failures.length} ${settingsStore.isEnglish ? 'failed' : '项失败'}`)
    else ElMessage.success(`${bulkSucceeded.value} ${settingsStore.isEnglish ? 'items completed' : '项已完成'}`)
  } finally {
    bulkBusy.value = false
    selectedDatasets.value = []
    selectedModels.value = []
  }
}
async function bulkDownloadDatasets() {
  await runBulk(selectedDatasets.value, async (row) => saveBlob(await downloadTrainingDataset(row.path), `${row.name}.zip`))
}
async function bulkRenameDatasets() {
  await runBulk(selectedDatasets.value, async (row) => {
    const result = await ElMessageBox.prompt(settingsStore.isEnglish ? 'New display name' : '新的显示名称', text.value.editDataset, { inputValue: row.displayName || row.name, confirmButtonText: text.value.save, cancelButtonText: text.value.cancel })
    return updateTrainingDatasetMetadata(row.path, { display_name: result.value.trim() })
  })
  await loadAssets()
}
async function bulkDeleteDatasets() {
  if (!await confirmDeletion()) return
  await runBulk(selectedDatasets.value, (row) => deleteTrainingDataset(row.path))
}
async function bulkDownloadModels() {
  await runBulk(selectedModels.value, async (row) => saveBlob(await downloadModelVersionApi(row.sceneId, row.id), row.modelName || `${row.version}.pt`))
}
async function bulkRenameModels(items = selectedModels.value) {
  await runBulk(items.filter((row) => canDelete(row)), async (row) => {
    const result = await ElMessageBox.prompt(settingsStore.isEnglish ? 'New model name' : '新的模型名称', text.value.model, { inputValue: row.modelName, confirmButtonText: text.value.save, cancelButtonText: text.value.cancel })
    return updateModelVersionApi(row.sceneId, row.id, { modelName: result.value.trim() })
  })
  await loadAssets()
}
async function bulkDeleteModels() {
  if (!await confirmDeletion()) return
  await runBulk(selectedModels.value.filter((row) => canDelete(row)), (row) => deleteModelVersionApi(row.sceneId, row.id))
}
async function retryModelCleanup(row) { try { await retryModelCleanupApi(row.sceneId, row.id); ElMessage.success(settingsStore.isEnglish ? 'Cleanup completed' : '清理完成'); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } }
async function uploadDataset(file) { if (!file.raw || uploadingDataset.value) return; uploadingDataset.value = true; pageError.value = ''; try { await uploadTrainingDataset(file.raw); ElMessage.success(text.value.upload); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } finally { uploadingDataset.value = false } }
function selectModelFile(file) { modelUpload.value.file=file.raw }
async function uploadModel() { const item=modelUpload.value; if(!item.sceneId || !item.version || !item.modelName || !item.file) return; uploading.value=true; try { await uploadModelVersionApi(item.sceneId,item); modelUploadVisible.value=false; modelUpload.value={sceneId:'',version:'',modelName:'',file:null}; ElMessage.success(text.value.upload); await loadAssets() } catch(error) { pageError.value=getApiErrorMessage(error,text.value.actionFailed) } finally { uploading.value=false } }
onMounted(loadAssets)
</script>
<style lang="scss" scoped>
.file-browser-page { max-width: 1200px; margin: 0 auto; padding: 0; }
.asset-card { margin-bottom: 18px; }
.asset-card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.bulk-actions { display: flex; gap: 6px; }
.bulk-progress { color: var(--app-text-secondary); font-size: 12px; margin-top: 6px; }
.bulk-failures { margin: 4px 0 0; padding-left: 18px; color: var(--el-color-danger); max-height: 120px; overflow: auto; }
.bulk-inline-actions { display: flex; justify-content: flex-end; margin: 6px 0; }
.asset-card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.resource-tools { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }
.resource-bulk-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
.asset-card-header > .bulk-actions { display: none !important; }
.resource-search { margin-bottom: 8px; }
.file-browser-page:not(.dataset-bulk-active) .dataset-card .bulk-actions,
.file-browser-page:not(.model-bulk-active) .model-card .bulk-actions,
.file-browser-page:not(.dataset-bulk-active) .dataset-card .bulk-inline-actions,
.file-browser-page:not(.model-bulk-active) .model-card .bulk-inline-actions { display: none; }
.dataset-card .bulk-actions .el-button:nth-child(2) { display: none; }
.dataset-card .bulk-actions .el-button:nth-child(3), .model-card .bulk-actions .el-button:nth-child(2) { display: none; }
.bulk-inline-actions .el-button { font-size: 0; min-width: 30px; padding: 6px 8px; }
.bulk-inline-actions .el-button::before { content: '✎'; font-size: 16px; line-height: 1; }
.inline-rename { appearance: none; border: 0; background: transparent; box-shadow: none; padding: 2px; color: #64748b; cursor: pointer; font-size: 16px; line-height: 1; }
.inline-rename:hover { color: #2563eb; }
.inline-rename:focus-visible { outline: 2px solid #93c5fd; outline-offset: 2px; border-radius: 2px; }
.asset-card .el-table .cell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-title { font-weight: 600; color: var(--app-text); }
.full-width { width: 100%; }
.cleanup-warning { margin-left: 6px; color: var(--el-color-warning); vertical-align: middle; }
</style>
