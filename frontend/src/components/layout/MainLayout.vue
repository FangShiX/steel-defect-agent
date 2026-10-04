<template>
  <div class="main-layout">
    <AppSidebar v-model:collapsed="collapsed" />

    <main :class="['layout-content', { 'layout-content--chat': route.name === 'Chat' }]">
      <router-view />
    </main>
    <TaskCenter />
    <div v-if="onboardingVisible" class="onboarding-overlay" @click.self="skipOnboarding">
      <section class="onboarding-card" role="dialog" aria-modal="true" :aria-label="onboardingText.title">
      <div class="onboarding-heading"><h2>{{ onboardingText.title }}</h2><button class="onboarding-close" type="button" @click="skipOnboarding">×</button></div>
      <p class="onboarding-subtitle">{{ onboardingText.subtitle }}</p>
      <div class="onboarding-progress"><span v-for="(step, index) in onboardingText.steps" :key="step.title" :class="{ active: index === onboardingStep, done: index < onboardingStep }" /></div>
      <div class="onboarding-step"><div class="step-index">{{ onboardingStep + 1 }}</div><h3>{{ currentOnboardingStep.title }}</h3><p>{{ currentOnboardingStep.description }}</p></div>
      <div class="onboarding-actions"><el-button text @click="skipOnboarding">{{ onboardingText.skip }}</el-button><span><el-button v-if="onboardingStep > 0" @click="onboardingStep -= 1">{{ onboardingText.previous }}</el-button><el-button type="primary" @click="nextOnboarding">{{ onboardingStep === onboardingText.steps.length - 1 ? onboardingText.finish : onboardingText.next }}</el-button></span></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import TaskCenter from '@/components/common/TaskCenter.vue'
import { useLlmStore } from '@/stores/llm'
import { useUserStore } from '@/stores/user'
import { useSettingsStore } from '@/stores/settings'

const narrowViewport = window.matchMedia?.('(max-width: 780px)')
const collapsed = ref(narrowViewport?.matches ?? false)
function syncSidebarWidth(event) {
  collapsed.value = event.matches
}
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const settingsStore = useSettingsStore()
const onboardingVisible = ref(false)
const onboardingStep = ref(0)
const onboardingText = computed(() => settingsStore.isEnglish ? {
  title: 'Get started with the platform',
  subtitle: 'Follow the path from upload to detection results. You can reopen the full guide from Help.',
  skip: 'Got it',
  previous: 'Previous', next: 'Next', finish: 'Finish',
  steps: [
    { title: 'Upload', description: 'Add a dataset, model or chat attachment.' },
    { title: 'Choose', description: 'Select a model or let Agent route the file.' },
    { title: 'Run', description: 'Start detection or training and keep the task ID.' },
    { title: 'Review', description: 'Inspect tools, references, results and reports.' },
  ],
} : {
  title: '\u9996\u6b21\u4f7f\u7528\u5f15\u5bfc',
  subtitle: '\u6309\u7167\u201c\u4e0a\u4f20\u2014\u9009\u62e9\u2014\u6267\u884c\u2014\u67e5\u770b\u201d\u5b8c\u6210\u7b2c\u4e00\u6b21\u4efb\u52a1\uff0c\u5b8c\u6574\u8bf4\u660e\u53ef\u5728\u201c\u5e2e\u52a9\u4e0e\u5f15\u5bfc\u201d\u4e2d\u91cd\u65b0\u67e5\u770b\u3002',
  skip: '\u77e5\u9053\u4e86',
  previous: '\u4e0a\u4e00\u6b65', next: '\u4e0b\u4e00\u6b65', finish: '\u5b8c\u6210',
  steps: [
    { title: '\u4e0a\u4f20', description: '\u6dfb\u52a0\u6570\u636e\u96c6\u3001\u6a21\u578b\u6216\u5bf9\u8bdd\u9644\u4ef6\u3002' },
    { title: '\u9009\u62e9', description: '\u9009\u62e9\u6a21\u578b\uff0c\u6216\u8ba9 Agent \u6839\u636e\u6587\u4ef6\u8def\u7531\u3002' },
    { title: '\u6267\u884c', description: '\u542f\u52a8\u68c0\u6d4b\u6216\u8bad\u7ec3\uff0c\u4fdd\u7559\u4efb\u52a1 ID\u3002' },
    { title: '\u67e5\u770b', description: '\u67e5\u770b\u5de5\u5177\u3001\u5f15\u7528\u3001\u7ed3\u679c\u548c\u62a5\u544a\u3002' },
  ],
})
const currentOnboardingStep = computed(() => onboardingText.value.steps[onboardingStep.value] || onboardingText.value.steps[0])

function onboardingKey() {
  return userStore.user?.id ? `ssdd_onboarding_seen_${userStore.user.id}` : ''
}

function completeOnboarding() {
  const key = onboardingKey()
  if (key) localStorage.setItem(key, '1')
  onboardingVisible.value = false
}

function skipOnboarding() { completeOnboarding() }
function nextOnboarding() {
  if (onboardingStep.value >= onboardingText.value.steps.length - 1) completeOnboarding()
  else onboardingStep.value += 1
}
function reopenOnboarding() {
  onboardingStep.value = 0
  onboardingVisible.value = true
}

onMounted(() => {
  narrowViewport?.addEventListener('change', syncSidebarWidth)
  document.documentElement.classList.add('app-shell-active')
  document.body.classList.add('app-shell-active')
  useLlmStore().fetchModels()
  window.addEventListener('open-onboarding', reopenOnboarding)
  if (route.name === 'Chat' && onboardingKey() && !localStorage.getItem(onboardingKey())) {
    onboardingVisible.value = true
  }
})

onUnmounted(() => {
  narrowViewport?.removeEventListener('change', syncSidebarWidth)
  document.documentElement.classList.remove('app-shell-active')
  document.body.classList.remove('app-shell-active')
  window.removeEventListener('open-onboarding', reopenOnboarding)
})
</script>

<style lang="scss" scoped>
.main-layout {
  position: fixed;
  inset: 0;
  width: 100%;
  height: auto;
  display: flex;
  align-items: flex-start;
}

.layout-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--app-bg);
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  padding: clamp(16px, 2vw, 28px);

  &.layout-content--chat {
    overflow: hidden;
    padding-bottom: 0;
  }

  > :deep(*) {
    width: min(100%, var(--app-content-max));
    margin-inline: auto;
  }
}

.onboarding-subtitle { margin: 0 0 22px; color: var(--app-text-secondary); line-height: 1.6; }
.onboarding-overlay { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 24px; background: rgba(15, 23, 42, .42); }
.onboarding-card { width: min(560px, 92vw); padding: 26px; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); }
.onboarding-heading, .onboarding-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.onboarding-heading h2 { margin: 0 0 8px; color: var(--app-text); font-size: 22px; }
.onboarding-close { border: 0; background: transparent; color: var(--app-text-secondary); font-size: 24px; cursor: pointer; }
.onboarding-progress { display: flex; gap: 7px; margin: 18px 0 24px; }
.onboarding-progress span { flex: 1; height: 3px; border-radius: 2px; background: var(--app-border); }
.onboarding-progress span.active, .onboarding-progress span.done { background: var(--el-color-primary); }
.onboarding-step { min-height: 145px; }
.step-index { color: var(--el-color-primary); font-size: 13px; font-weight: 700; }
.onboarding-step h3 { margin: 10px 0 8px; color: var(--app-text); }
.onboarding-step p { color: var(--app-text-secondary); line-height: 1.6; }

:global(html.app-shell-active),
:global(body.app-shell-active),
:global(body.app-shell-active #app) {
  width: 100%;
  height: 100%;
  overflow: hidden;
}
</style>
