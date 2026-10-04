<template>
  <article class="stat-card" :style="{ '--accent': accent }">
    <div class="stat-card__icon">
      <el-icon><component :is="icon" /></el-icon>
    </div>
    <div class="stat-card__body">
      <span>{{ label }}</span>
      <strong>{{ displayValue }}<small v-if="unit">{{ unit }}</small></strong>
      <p v-if="helper">{{ helper }}</p>
    </div>
  </article>
</template>

<script setup>
import { computed } from "vue";
import { useSettingsStore } from '@/stores/settings'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  unit: { type: String, default: "" },
  helper: { type: String, default: "" },
  icon: { type: [Object, Function], required: true },
  accent: { type: String, default: "#2563eb" },
  decimals: { type: Number, default: 0 },
});

const settingsStore = useSettingsStore()

const displayValue = computed(() => {
  if (typeof props.value !== "number") return props.value;
  return props.value.toLocaleString(settingsStore.isEnglish ? "en-US" : "zh-CN", {
    minimumFractionDigits: props.decimals,
    maximumFractionDigits: props.decimals,
  });
});
</script>

<style lang="scss" scoped>
.stat-card {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 15px;
  padding: 20px;
  border: 1px solid #e7ebf1;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(28, 39, 60, 0.05);
}

.stat-card__icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 12px;
  background: color-mix(in srgb, var(--accent) 12%, white);
  color: var(--accent);
  font-size: 22px;
}

.stat-card__body {
  min-width: 0;

  span {
    color: $text-secondary;
    font-size: 12px;
  }

  strong {
    display: block;
    margin-top: 4px;
    color: #172033;
    font-size: 25px;
    line-height: 1.2;

    small {
      margin-left: 4px;
      color: $text-secondary;
      font-size: 12px;
      font-weight: 500;
    }
  }

  p {
    overflow: hidden;
    margin: 5px 0 0;
    color: #98a2b3;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
</style>
