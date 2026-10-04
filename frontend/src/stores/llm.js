/**
 * LLM 模型状态管理
 * 启动时自动从后端拉取可用模型列表
 */
import { defineStore } from 'pinia'
import { getLlmModels } from '@/api/llm'

export const DEFAULT_LLM_MODEL_VALUE = '__default__'

const FALLBACK_MODELS = [
  {
    id: DEFAULT_LLM_MODEL_VALUE,
    label: '后端默认对话模型',
    owned_by: '未获取到模型列表',
  },
]

export const useLlmStore = defineStore('llm', {
  state: () => ({
    /** 可用模型列表 [{ id, owned_by }] */
    models: [],
    /** 是否正在加载 */
    loading: false,
    /** 是否已加载过 */
    loaded: false,
    /** 错误信息 */
    error: null,
    /** LLM 提供商 */
    provider: null,
  }),

  getters: {
    /** 是否有可用模型 */
    hasModels: (state) => state.models.length > 0,

    /** 推荐模型（优先后端真实列表，否则使用后端默认配置） */
    defaultModel: (state) => {
      if (!state.models.length) return DEFAULT_LLM_MODEL_VALUE
      const preferred = state.models.find(m => m.id === 'qwen3.7-plus')
      if (preferred) return preferred.id
      // fallback: qwen-plus > qwen-max > first model
      for (const fallback of ['qwen-plus', 'qwen-max']) {
        const found = state.models.find(m => m.id === fallback)
        if (found) return found.id
      }
      return state.models[0].id
    },

    /** 格式化的模型选项列表（供下拉组件使用） */
    modelOptions: (state) => {
      const source = state.models.length ? state.models : FALLBACK_MODELS
      return source.map((m) => ({
        label: m.label || m.id,
        value: m.id,
        ownedBy: m.owned_by,
      }))
    },
  },

  actions: {
    /**
     * 从后端拉取可用模型列表
     */
    async fetchModels() {
      if (this.loading || this.loaded) return
      this.loading = true
      this.error = null
      try {
        const data = await getLlmModels()
        this.models = data?.models?.length ? data.models : FALLBACK_MODELS
        this.provider = data?.provider ?? null
        this.loaded = true
      } catch (err) {
        this.error = err?.response?.data?.detail || '获取模型列表失败'
        this.models = FALLBACK_MODELS
        this.loaded = true
        // 未配置 API Key 时不弹错误，仅记录
        console.warn('[LLM Store] 获取模型列表失败:', this.error)
      } finally {
        this.loading = false
      }
    },
  },
})
