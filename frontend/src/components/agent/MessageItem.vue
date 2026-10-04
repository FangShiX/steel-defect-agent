<template>
  <!-- User message: subtle, right-aligned chip -->
  <div v-if="message.role === 'user'" class="user-msg">
    <div v-if="message.imagePreviewUrls?.length" class="user-images">
      <img
        v-for="(url, i) in message.imagePreviewUrls"
        v-show="url"
        :key="i"
        :src="url"
        class="user-image"
        :alt="text.uploadAlt"
      />
    </div>
    <div v-if="message.attachments?.length" class="user-attachments">
      <div v-for="(attachment, i) in message.attachments" :key="`${attachment.name || 'attachment'}-${i}`" class="user-attachment">
        <video v-if="attachment.content_type?.startsWith('video/') && attachment.previewUrl" class="user-video" :src="attachment.previewUrl" controls preload="metadata" />
        <span>{{ attachment.name || 'attachment' }}</span>
      </div>
    </div>
    <span v-if="message.content" class="user-text">{{ message.content }}</span>
  </div>

  <!-- Assistant message: centered, prominent, no avatar -->
  <div v-else class="assistant-msg">
    <div class="assistant-content">
      <div v-if="message.toolCalls?.length" class="message-tool-header">
        <div v-if="agentLabel" class="agent-label">
          <span v-if="agentIcon" class="agent-icon" v-html="agentIcon" />
          <span>{{ displayAgentLabel(agentLabel) }}</span>
        </div>
        <div class="tool-trace">
          <div
            v-for="tool in message.toolCalls"
            :key="tool.id || tool.name || tool.tool_name"
            class="tool-trace-item"
          >
            <span class="tool-name">{{ getToolName(tool) }}</span>
            <el-tag :type="getToolTag(tool)" size="small">{{ getToolStatus(tool) }}</el-tag>
            <span v-if="getToolResource(tool)" class="tool-resource">{{ text.resource }}: {{ getToolResource(tool) }}</span>
          </div>
        </div>
      </div>

      <DetectionResultCard
        v-if="message.detectionResult"
        :result="message.detectionResult"
        :preview-url="message.detectionPreviewUrl"
      />
      <AgentResultCard
        v-for="card in message.toolResultCards || []"
        :key="card.id"
        :card="card"
      />
      <div class="markdown-body" v-html="renderedContent" />

      <el-alert
        v-if="message.status === 'error'"
        :title="message.errorMessage || text.agentError"
        type="error"
        :closable="false"
        show-icon
        class="message-error"
      />
    </div>

    <div v-if="!isLastStreaming && message.content" class="msg-footer">
      <button class="footer-btn" :class="{ copied }" :title="text.copy" @click="handleCopy">
        <el-icon :size="14"><DocumentCopy v-if="!copied" /><Check v-else /></el-icon>
        <span>{{ copied ? text.copied : text.copy }}</span>
      </button>
      <button class="footer-btn" :title="text.regenerate" @click="$emit('regenerate', message)">
        <el-icon :size="14"><Refresh /></el-icon>
        <span>{{ text.regenerate }}</span>
      </button>
      <span class="msg-time">{{ formattedTime }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { DocumentCopy, Check, Refresh } from '@element-plus/icons-vue'
import { useSettingsStore } from '@/stores/settings'
import { renderMarkdown } from '@/utils/markdown'
import AgentResultCard from './AgentResultCard.vue'
import { AGENT_ICON_BY_NAME } from '@/stores/agent'
const AGENT_LABEL_BY_NAME = {
  detection: '检测 Agent',
  data: '数据 Agent',
  general: '通用 Agent',
  training: '训练 Agent',
}
import DetectionResultCard from './DetectionResultCard.vue'

const props = defineProps({
  message: { type: Object, required: true },
  isLastStreaming: { type: Boolean, default: false },
})

defineEmits(['regenerate'])

const copied = ref(false)
const settingsStore = useSettingsStore()
let copyTimer = null

const text = computed(() => settingsStore.isEnglish ? {
  uploadAlt: 'Uploaded image',
  agentError: 'Agent response failed. Please try again.',
  copy: 'Copy',
  copied: 'Copied',
  regenerate: 'Regenerate',
  called: 'Called',
  running: 'Running',
  success: 'Success',
  error: 'Failed',
  singleTool: 'Single-image detection tool',
  batchTool: 'Batch detection tool',
  zipTool: 'ZIP detection tool',
  videoTool: 'Video detection tool',
  detectionTool: 'Defect detection tool',
  historyTool: 'Detection history tool',
  knowledgeTool: 'Knowledge search tool',
} : {
  resource: '\u8d44\u6e90',
  openTask: '\u6253\u5f00\u4efb\u52a1',
  document: '\u6587\u6863',
  chunk: '\u5206\u5757',
  request: 'Request ID',
  session: '\u4f1a\u8bdd',
  task: '\u4efb\u52a1',
  uploadAlt: '上传图片',
  agentError: '智能体响应失败，请重试',
  copy: '复制',
  copied: '已复制',
  regenerate: '重新生成',
  called: '已调用',
  running: '运行中',
  success: '成功',
  error: '失败',
  singleTool: '单图检测工具',
  batchTool: '批量检测工具',
  zipTool: 'ZIP 检测工具',
  videoTool: '视频检测工具',
  detectionTool: '缺陷检测工具',
  historyTool: '检测历史工具',
  knowledgeTool: '知识库检索工具',
})

const renderedContent = computed(() => {
  return renderMarkdown(props.message.content || '')
})

const agentName = computed(() => {
  return props.message.toolCalls?.find(t => t.agent)?.agent || ''
})

const agentLabel = computed(() => {
  if (agentName.value) return AGENT_LABEL_BY_NAME?.[agentName.value] || agentName.value
  return props.message.toolCalls?.find(t => t.agentLabel)?.agentLabel || ''
})

const agentIcon = computed(() => {
  return AGENT_ICON_BY_NAME[agentName.value] || ''
})

function displayAgentLabel(label) {
  const zhToEn = {
    '🔍 检测 Agent': 'Detection Agent',
    '📊 数据 Agent': 'Data Agent',
    '💬 通用 Agent': 'General Agent',
    detection: 'Detection Agent',
    data: 'Data Agent',
    general: 'General Agent',
  }
  const enToZh = {
    detection: '检测 Agent',
    data: '数据 Agent',
    general: '通用 Agent',
  }
  return settingsStore.isEnglish ? (zhToEn[label] || label) : (enToZh[label] || label)
}

const formattedTime = computed(() => {
  if (!props.message.createdAt) return ''
  return new Date(props.message.createdAt).toLocaleTimeString(undefined, {
    hour: 'numeric', minute: '2-digit',
  })
})

function handleCopy() {
  const text = props.message.content || ''
  navigator.clipboard.writeText(text).then(() => {
    copied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 2000)
  }).catch(() => {})
}

function getToolName(tool) {
  const name = tool.name || tool.tool_name || 'tool'
  const map = {
    detect_single: text.value.singleTool,
    detect_batch: text.value.batchTool,
    detect_zip: text.value.zipTool,
    detect_video: text.value.videoTool,
    detection_tool: text.value.detectionTool,
    history_query: text.value.historyTool,
    knowledge_search: text.value.knowledgeTool,
  }
  return map[name] || name
}

function getToolStatus(tool) {
  const map = {
    running: text.value.running,
    success: text.value.success,
    error: text.value.error,
  }
  return map[tool.status] || text.value.called
}

function getToolTag(tool) {
  if (tool.status === 'success') return 'success'
  if (tool.status === 'error') return 'danger'
  return 'warning'
}

function getToolResource(tool) {
  const value = tool.task_id
    || tool.taskId
    || tool.file_id
    || tool.fileId
    || tool.knowledge_document_id
    || tool.knowledgeDocumentId
    || tool.model_id
    || tool.modelId
  return value == null || value === '' ? '' : String(value)
}

</script>

<style lang="scss" scoped>
/* ── User message: subtle right-aligned chip, same max-width as assistant ── */
.user-msg {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  max-width: 780px;
  margin: 0 auto 4px;
  padding: 6px 24px;
}

.user-images {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 70%;
}

.user-attachments {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 70%;
}

.user-attachment {
  max-width: 240px;
  overflow: hidden;
  padding: 5px 10px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-video { display: block; width: min(280px, 100%); max-height: 160px; border-radius: 6px; background: #111827; }

.user-image {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--app-border);
}

.user-text {
  display: inline-block;
  max-width: 70%;
  padding: 6px 14px;
  background: var(--app-active);
  color: var(--app-text);
  border-radius: 20px;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Assistant message: centered, prominent ── */
.assistant-msg {
  padding: 16px 24px;
  margin-bottom: 8px;
}

.assistant-content {
  max-width: 780px;
  margin: 0 auto;

  .markdown-body {
    font-size: 15px;
    line-height: 1.75;
    color: var(--app-text);

    :deep(p) {
      margin: 0 0 12px;
    }
    :deep(p:last-child) {
      margin-bottom: 0;
    }
    :deep(h1), :deep(h2), :deep(h3), :deep(h4) {
      margin: 20px 0 10px;
      font-weight: 600;
      color: var(--app-text);
    }
    :deep(h1) { font-size: 1.4em; }
    :deep(h2) { font-size: 1.2em; }
    :deep(h3) { font-size: 1.1em; }
    :deep(ul), :deep(ol) {
      padding-left: 20px;
      margin: 8px 0;
    }
    :deep(li) {
      margin: 4px 0;
    }
    :deep(code) {
      background: var(--app-subtle);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 13px;
      font-family: 'SF Mono', 'Fira Code', monospace;
    }
    :deep(pre) {
      background: var(--app-subtle);
      border: 1px solid var(--app-border);
      padding: 14px 16px;
      border-radius: 10px;
      overflow-x: auto;
      margin: 12px 0;
    }
    :deep(pre code) {
      background: transparent;
      padding: 0;
    }
    :deep(blockquote) {
      border-left: 3px solid #8F8AB0;
      margin: 12px 0;
      padding: 4px 14px;
      color: var(--app-muted);
    }
    :deep(table) {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
    }
    :deep(th), :deep(td) {
      border: 1px solid var(--app-border);
      padding: 8px 12px;
      text-align: left;
      font-size: 14px;
    }
    :deep(th) {
      background: var(--app-subtle);
      font-weight: 600;
    }
  }
}
/* ── Footer: actions ── */
.msg-footer {
  max-width: 780px;
  margin: 8px auto 0;
  display: flex;
  align-items: center;
  gap: 4px;
}

.footer-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #a3a3a3;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    color: var(--app-text);
    background: var(--app-hover);
  }

  &.copied {
    color: #67c23a;
  }
}

.msg-time {
  margin-left: 4px;
  font-size: 11px;
  color: #c0c4cc;
}

.tool-trace {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface);
}

.message-tool-header {
  margin-bottom: 14px;
}

.agent-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 0 0 6px 2px;
  color: #8F8AB0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.agent-icon {
  display: inline-flex;
  align-items: center;
}

.tool-trace-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.tool-name {
  color: var(--app-text);
}
.tool-resource {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-error {
  margin-top: 12px;
}

</style>
