<template>
  <section class="agent-result-card">
    <header class="agent-result-header">
      <div>
        <p class="agent-result-kicker">{{ text.kicker }}</p>
        <strong>{{ title }}</strong>
      </div>
      <el-tag :type="statusType" effect="light" size="small">{{ statusText }}</el-tag>
    </header>

    <div v-if="metaRows.length" class="agent-result-meta">
      <div v-for="row in metaRows" :key="row.label">
        <span>{{ row.label }}</span>
        <strong>{{ row.value }}</strong>
      </div>
    </div>

    <template v-if="card.type === 'statistics'">
      <div class="agent-result-grid">
        <div>
          <span>{{ text.tasks }}</span>
          <strong>{{ result.total_tasks || 0 }}</strong>
        </div>
        <div>
          <span>{{ text.images }}</span>
          <strong>{{ result.total_images || 0 }}</strong>
        </div>
        <div>
          <span>{{ text.defects }}</span>
          <strong>{{ result.total_objects || 0 }}</strong>
        </div>
      </div>
    </template>

    <template v-else-if="card.type === 'video_result'">
      <video
        v-if="result.annotatedVideoUrl || result.annotated_video_url"
        :src="result.annotatedVideoUrl || result.annotated_video_url"
        class="agent-result-video"
        controls
        preload="metadata"
      />
      <div class="agent-result-grid compact">
        <div>
          <span>{{ text.frames }}</span>
          <strong>{{ result.processedFrames ?? result.processed_frames ?? 0 }}</strong>
        </div>
        <div>
          <span>{{ text.defects }}</span>
          <strong>{{ result.totalObjects ?? result.total_objects ?? 0 }}</strong>
        </div>
        <div>
          <span>{{ text.duration }}</span>
          <strong>{{ result.durationSeconds ?? result.duration_seconds ?? 0 }}s</strong>
        </div>
      </div>
    </template>

    <template v-else-if="card.type === 'history'">
      <div v-if="historyRows.length" class="agent-result-list">
        <article v-for="task in historyRows" :key="task.id || task.task_id" class="agent-result-row">
          <strong>#{{ task.id || task.task_id }}</strong>
          <span>{{ task.scene_name || task.task_type || text.unknown }}</span>
          <el-tag size="small" effect="plain">{{ task.status || text.unknown }}</el-tag>
        </article>
      </div>
      <el-empty v-else :image-size="56" :description="text.noHistory" />
    </template>

    <template v-else-if="card.type === 'knowledge_citations'">
      <div v-if="citationRows.length" class="agent-result-list">
        <article v-for="(item, index) in citationRows" :key="index" class="agent-result-citation">
          <strong>{{ item.document_title || item.title || text.knowledgeDocument }}</strong>
          <p>{{ item.content || item.text || item.chunk || text.noCitationContent }}</p>
          <span v-if="item.score != null">{{ text.score }} {{ Number(item.score).toFixed(3) }}</span>
        </article>
      </div>
      <el-empty v-else :image-size="56" :description="result.message || text.noKnowledge" />
    </template>

    <template v-else>
      <el-alert
        v-if="card.status === 'error'"
        :title="result.message || result.error || text.toolFailed"
        type="error"
        :closable="false"
        show-icon
      />
      <p v-else class="agent-result-message">{{ result.message || text.toolDone }}</p>
    </template>

    <footer v-if="actionRows.length" class="agent-result-actions">
      <router-link
        v-for="action in actionRows"
        :key="action.label"
        class="agent-result-action"
        :to="action.to"
      >
        {{ action.label }}
      </router-link>
    </footer>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  card: {
    type: Object,
    required: true,
  },
})

const settingsStore = useSettingsStore()

const text = computed(() => settingsStore.isEnglish ? {
  kicker: 'Agent result',
  statistics: 'Detection statistics',
  history: 'Detection history',
  knowledge: 'RAG references',
  toolResult: 'Tool result',
  video: 'Video result',
  success: 'Completed',
  failed: 'Failed',
  toolFailed: 'Tool call failed',
  tasks: 'Tasks',
  images: 'Images',
  defects: 'Defects',
  frames: 'Key frames',
  duration: 'Duration',
  taskId: 'Task ID',
  modelId: 'Model',
  fileId: 'File',
  documentId: 'Knowledge document',
  order: 'Order',
  snapshot: 'Snapshot',
  unknown: 'Unknown',
  noHistory: 'No detection history returned',
  knowledgeDocument: 'Knowledge document',
  noCitationContent: 'No citation content',
  noKnowledge: 'No related knowledge found',
  score: 'Score',
  toolDone: 'Tool call completed',
  openTask: 'Open task',
  openFile: 'Open file',
  openKnowledge: 'Open source',
} : {
  kicker: 'Agent 结果',
  statistics: '检测统计',
  history: '检测历史',
  knowledge: 'RAG 引用',
  toolResult: '工具结果',
  video: '视频结果',
  success: '已完成',
  failed: '失败',
  toolFailed: '工具调用失败',
  tasks: '任务',
  images: '图片',
  defects: '缺陷',
  frames: '关键帧',
  duration: '时长',
  taskId: '任务 ID',
  modelId: '模型',
  fileId: '文件',
  documentId: '知识文档',
  order: '顺序',
  snapshot: '快照',
  unknown: '未知',
  noHistory: '未返回检测历史',
  knowledgeDocument: '知识库文档',
  noCitationContent: '暂无引用内容',
  noKnowledge: '未找到相关知识',
  score: '相似度',
  toolDone: '工具调用已完成',
  openTask: '查看任务',
  openFile: '查看文件',
  openKnowledge: '查看来源',
})

const result = computed(() => props.card.result || {})

const title = computed(() => ({
  statistics: text.value.statistics,
  history: text.value.history,
  knowledge_citations: text.value.knowledge,
  video_result: text.value.video,
}[props.card.type] || props.card.title || text.value.toolResult))

const statusText = computed(() => props.card.status === 'error' ? text.value.failed : text.value.success)
const statusType = computed(() => props.card.status === 'error' ? 'danger' : 'success')

const metaRows = computed(() => {
  const source = {
    taskId: props.card.task_id || props.card.taskId || result.value.task_id || result.value.taskId,
    modelId: props.card.model_id || props.card.modelId || result.value.model_id || result.value.modelId,
    fileId: props.card.file_id || props.card.fileId || result.value.file_id || result.value.fileId,
    documentId: props.card.knowledge_document_id || props.card.knowledgeDocumentId || result.value.knowledge_document_id || result.value.knowledgeDocumentId,
    order: props.card.display_order ?? props.card.displayOrder,
    snapshot: props.card.snapshot_id || props.card.snapshotId,
  }
  return [
    [text.value.taskId, source.taskId],
    [text.value.modelId, source.modelId],
    [text.value.fileId, source.fileId],
    [text.value.documentId, source.documentId],
    [text.value.order, source.order],
    [text.value.snapshot, source.snapshot],
  ]
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([label, value]) => ({ label, value }))
})

const historyRows = computed(() => result.value.tasks || result.value.items || [])
const citationRows = computed(() => result.value.results || result.value.citations || [])

const actionRows = computed(() => {
  const taskId = props.card.task_id || props.card.taskId || result.value.task_id || result.value.taskId
  const fileId = props.card.file_id || props.card.fileId || result.value.file_id || result.value.fileId
  const documentId = props.card.knowledge_document_id || props.card.knowledgeDocumentId || result.value.knowledge_document_id || result.value.knowledgeDocumentId
  return [
    taskId ? { label: text.value.openTask, to: { path: '/history', query: { taskId } } } : null,
    fileId ? { label: text.value.openFile, to: { path: '/files', query: { fileId } } } : null,
    documentId ? { label: text.value.openKnowledge, to: { path: '/files', query: { knowledgeDocumentId: documentId } } } : null,
  ].filter(Boolean)
})
</script>

<style lang="scss" scoped>
.agent-result-card {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
  box-shadow: var(--app-shadow);
  color: var(--app-text);
}

.agent-result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  strong {
    font-size: 15px;
  }
}

.agent-result-kicker {
  margin: 0 0 3px;
  color: #8f8ab0;
  font-size: 12px;
  font-weight: 700;
}

.agent-result-meta,
.agent-result-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;

  div {
    min-width: 0;
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--app-subtle);
  }

  span,
  strong {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    color: var(--app-muted);
    font-size: 12px;
  }

  strong {
    margin-top: 3px;
    color: var(--app-text);
    font-size: 14px;
  }
}

.agent-result-grid.compact {
  margin-top: 10px;
  margin-bottom: 0;
}

.agent-result-video {
  display: block;
  width: 100%;
  max-height: 380px;
  border-radius: 10px;
  background: #000;
}

.agent-result-list {
  display: grid;
  gap: 8px;
}

.agent-result-row,
.agent-result-citation {
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-subtle);
}

.agent-result-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;

  span {
    overflow: hidden;
    color: var(--app-muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.agent-result-citation {
  strong {
    display: block;
    margin-bottom: 5px;
  }

  p {
    margin: 0;
    color: var(--app-muted);
    line-height: 1.6;
  }

  span {
    display: inline-block;
    margin-top: 6px;
    color: #8f8ab0;
    font-size: 12px;
  }
}

.agent-result-message {
  margin: 0;
  color: var(--app-muted);
}

.agent-result-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.agent-result-action {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 10px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  color: #5f8df7;
  text-decoration: none;
  font-size: 12px;

  &:hover {
    background: var(--app-hover);
  }
}

@media (max-width: 720px) {
  .agent-result-meta,
  .agent-result-grid {
    grid-template-columns: 1fr;
  }

  .agent-result-row {
    grid-template-columns: 1fr;
  }
}
</style>
