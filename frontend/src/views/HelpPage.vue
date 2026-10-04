<template>
  <div class="help-page">
    <ModulePageHeader :title="text.title" :description="text.subtitle" />
    <div class="help-actions"><el-button @click="reopenOnboarding">重新查看首次使用引导</el-button></div>
    <div class="help-grid">
      <el-card v-for="(step, index) in steps" :key="step.title" shadow="never" class="help-card">
        <div class="step-number">{{ index + 1 }}</div><h3>{{ step.title }}</h3><p>{{ step.description }}</p>
        <router-link v-if="step.to" :to="step.to" class="step-link">{{ text.open }}</router-link>
      </el-card>
    </div>
    <el-card shadow="never" class="help-card requirements"><h3>{{ text.formats }}</h3><p>{{ text.formatDescription }}</p><ul><li>{{ text.images }}</li><li>{{ text.videos }}</li><li>{{ text.datasets }}</li><li>{{ text.models }}</li></ul></el-card>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import ModulePageHeader from '@/components/common/ModulePageHeader.vue'
const settingsStore = useSettingsStore()
function reopenOnboarding() { window.dispatchEvent(new CustomEvent('open-onboarding')) }
const text = computed(() => settingsStore.isEnglish ? {
  title: 'Getting started', subtitle: 'Upload data, choose a model, run a task and inspect the evidence.', open: 'Open', formats: 'Supported formats and limits', formatDescription: 'Files are checked on the server before processing.', images: 'Images: JPG, JPEG, PNG, BMP, WEBP, TIF, TIFF.', videos: 'Videos: configured formats within the server size limit.', datasets: 'Datasets: ZIP with data.yaml and valid YOLO labels.', models: 'Models: .pt files within the configured upload limit.',
} : {
  title: '首次使用引导', subtitle: '上传数据、选择模型、创建任务并查看可追溯结果。', open: '打开', formats: '格式要求与限制', formatDescription: '文件会在服务端校验后再处理。', images: '图片：JPG、JPEG、PNG、BMP、WEBP、TIF、TIFF。', videos: '视频：服务端允许的格式及大小限制。', datasets: '数据集：包含 data.yaml 和有效 YOLO 标签的 ZIP。', models: '模型：在配置大小限制内的 .pt 文件。',
})
const steps = computed(() => settingsStore.isEnglish ? [
  { title: 'Upload or attach data', description: 'Use Files for datasets and models, or attach a file directly in Chat.', to: '/files' }, { title: 'Choose a model', description: 'Select a scene model or let the Agent route image attachments to detection.', to: '/files' }, { title: 'Run a task', description: 'Start single, batch, ZIP, video or training tasks and keep the task ID.', to: '/detection' }, { title: 'Review results', description: 'Open task details, tool calls, references, metrics and reports.', to: '/history' },
] : [
  { title: '上传或附加数据', description: '在文件页面管理数据集和模型，也可以直接在对话中附加文件。', to: '/files' }, { title: '选择模型', description: '选择场景模型；图片附件会自动路由到检测 Agent。', to: '/files' }, { title: '创建任务', description: '启动单图、批量、ZIP、视频或训练任务，并保留任务 ID。', to: '/detection' }, { title: '查看结果', description: '查看工具调用、资源引用、指标和导出报告。', to: '/history' },
])
</script>
<style scoped lang="scss">
.help-page { max-width: 1100px; margin: 0 auto; }.help-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }.help-card { position: relative; }.step-number { width: 30px; height: 30px; border-radius: 50%; background: var(--el-color-primary); color: #fff; display: grid; place-items: center; font-weight: 700; } h3 { margin: 14px 0 8px; color: var(--app-text); } p, li { color: var(--app-text-secondary); line-height: 1.55; font-size: 13px; }.step-link { color: var(--el-color-primary); font-size: 13px; }.requirements { margin-top: 14px; } @media (max-width: 900px) { .help-grid { grid-template-columns: repeat(2, 1fr); } } @media (max-width: 520px) { .help-grid { grid-template-columns: 1fr; } }
</style>
