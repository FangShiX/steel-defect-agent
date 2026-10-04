<template>
  <div class="chart-panel" :class="{ 'is-loading': loading }">
    <div v-if="title || subtitle" class="chart-panel__heading">
      <div>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <slot name="extra" />
    </div>
    <div v-if="loading" class="chart-panel__state">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>{{ text.loading }}</span>
    </div>
    <el-empty
      v-else-if="empty"
      class="chart-panel__state"
      :image-size="72"
      :description="text.empty"
    />
    <div v-show="!loading && !empty" ref="chartRef" :style="chartStyle" />
  </div>
</template>

<script setup>
import { Loading } from "@element-plus/icons-vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useSettingsStore } from '@/stores/settings'
import echarts from '@/utils/echarts'

const props = defineProps({
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
  option: { type: Object, required: true },
  height: { type: [Number, String], default: 300 },
  loading: { type: Boolean, default: false },
  empty: { type: Boolean, default: false },
});

const settingsStore = useSettingsStore()
const text = computed(() => settingsStore.isEnglish
  ? { loading: 'Loading chart data', empty: 'No data for the current filters' }
  : { loading: '正在加载图表数据', empty: '当前筛选条件下暂无数据' },
)

const chartRef = ref();
let chart;
let resizeObserver;

const chartStyle = computed(() => ({
  width: "100%",
  height: typeof props.height === "number" ? `${props.height}px` : props.height,
}));

async function renderChart() {
  if (props.loading || props.empty || !chartRef.value) return;
  await nextTick();
  if (!chart) {
    chart = echarts.init(chartRef.value, null, { renderer: "canvas" });
  }
  chart.setOption(props.option, { notMerge: true, lazyUpdate: true });
  chart.resize();
}

watch(() => props.option, renderChart, { deep: true });
watch(() => [props.loading, props.empty], renderChart);

onMounted(() => {
  renderChart();
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => chart?.resize());
    resizeObserver.observe(chartRef.value);
  } else {
    window.addEventListener("resize", renderChart);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  window.removeEventListener("resize", renderChart);
  chart?.dispose();
  chart = undefined;
});
</script>

<style lang="scss" scoped>
.chart-panel {
  min-width: 0;
  padding: 20px;
  border: 1px solid #e7ebf1;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(28, 39, 60, 0.05);
}

.chart-panel__heading {
  display: flex;
  justify-content: space-between;
  gap: $spacing-md;
  margin-bottom: 12px;

  h3 {
    margin: 0;
    color: #1f2937;
    font-size: 16px;
  }

  p {
    margin: 5px 0 0;
    color: $text-secondary;
    font-size: 12px;
  }
}

.chart-panel__state {
  display: flex;
  min-height: 260px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: $text-secondary;
}
</style>
