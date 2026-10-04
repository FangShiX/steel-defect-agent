<template>
  <div class="dashboard-page">
    <!-- header bar -->
    <div class="dash-header">
      <span class="dash-title">数据看板</span>
      <div class="dash-header-right">
        <el-select v-model="filters.mediaType" class="format-select" @change="loadDashboard">
          <el-option v-for="option in mediaTypeOptions" :key="option.value || 'all'" :label="option.label" :value="option.value" />
        </el-select>
        <div class="period-wrap" ref="periodRef">
        <button class="period-trigger" @click="menuOpen = !menuOpen">
          <span class="period-label">时间维度</span>
          <span class="period-val">{{ currentPeriodLabel }}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <Teleport to="body">
          <div v-if="menuOpen" class="period-overlay" @click="closeMenu" />
          <transition name="period-drop">
            <div v-if="menuOpen" class="period-dropdown" :style="dropStyle" @click.stop>
              <div
                v-for="opt in periodOptions"
                :key="opt.value"
                :class="['period-item', { active: period === opt.value }]"
                @click="selectPeriod(opt.value)"
              >{{ opt.label }}</div>
            </div>
          </transition>
          <transition name="period-drop">
            <div v-if="menuOpen && period === 'custom'" class="period-cal-panel" :style="calPanelStyle" @click.stop>
              <div class="period-calendar">
                <div class="cal-month" v-for="(m, mi) in calendarMonths" :key="mi">
                  <div class="cal-month-head">
                    <button v-if="mi === 0" class="cal-nav" @click.stop="calMonthOffset--">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m15 18-6-6 6-6"/></svg>
                    </button>
                    <span v-else class="cal-nav-spacer" />
                    <span class="cal-month-title">{{ m.label }}</span>
                    <button v-if="mi === 1" class="cal-nav" @click.stop="calMonthOffset++">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m9 18 6-6-6-6"/></svg>
                    </button>
                    <span v-else class="cal-nav-spacer" />
                  </div>
                  <div class="cal-weekdays">
                    <span v-for="d in weekDays" :key="d" class="cal-wd">{{ d }}</span>
                  </div>
                  <div class="cal-grid">
                    <span
                      v-for="(day, di) in m.days"
                      :key="di"
                      :class="calDayClass(day)"
                      @click.stop="pickDate(day)"
                    >{{ day ? day.label : '' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </transition>
        </Teleport>
      </div>
      <button class="period-trigger refresh-btn" :disabled="loading" @click="exportDashboard">
        <span class="period-val">{{ settingsStore.isEnglish ? 'Export CSV' : '导出 CSV' }}</span>
      </button>
      <button class="period-trigger refresh-btn" :disabled="loading" @click="loadDashboard">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: loading }"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>
        <span class="period-val">{{ text.refresh }}</span>
      </button>
      </div>
    </div>

    <section v-if="false" class="dashboard-filter-bar">
      <el-input v-model="filters.keyword" clearable :placeholder="text.keyword" @keyup.enter="loadDashboard" />
      <el-select v-model="filters.taskType" clearable :placeholder="text.allTypes">
        <el-option v-for="option in taskTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-select v-model="filters.mediaType" clearable :placeholder="text.mediaType">
        <el-option v-for="option in mediaTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-select v-model="filters.sceneId" clearable :placeholder="text.allScenes">
        <el-option v-for="scene in scenes" :key="scene.id" :label="scene.displayName || scene.name" :value="scene.id" />
      </el-select>
      <el-select v-model="filters.status" clearable :placeholder="text.allStatuses">
        <el-option v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-input v-if="userStore.isSuperuser" v-model="filters.ownerUserId" clearable :placeholder="text.userId" />
      <el-button type="primary" @click="loadDashboard">{{ text.applyFilters }}</el-button>
      <el-select v-model="viewGranularity" :placeholder="text.viewGranularity">
        <el-option v-for="option in granularityOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-button @click="openFilteredHistory">{{ text.openView }}</el-button>
    </section>

    <PageErrorAlert
      v-if="pageError"
      :message="pageError"
      :retry-text="text.reload"
      @retry="loadDashboard"
    />

    <!-- metric header + cards + chart on same row -->
    <div class="dash-top-row">
      <div class="side-left">
        <div class="chart-metric-header">
          <div class="chart-metric-label">检测次数</div>
          <div class="chart-metric-row">
            <span class="chart-metric-value">{{ trendTotal }}</span>
            <span class="chart-pill blue">{{ trendChangeText }}</span>
            <span class="chart-pill blue-light">{{ trendPrevTotal }} 次</span>
          </div>
          <div class="chart-compare-row">
            <span class="chart-compare-label">vs</span>
            <span class="chart-compare-date" ref="trendCompareRef" @click.stop="toggleTrendCompareCal">
              {{ trendDateLabel }}
              <svg class="cal-arrow" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="m12 15.41 5.71-5.7-1.42-1.42-4.29 4.3-4.29-4.3-1.42 1.42z"/></svg>
            </span>
            <Teleport to="body">
              <div v-if="trendCompareOpen" class="period-overlay" @click="trendCompareOpen = false" />
              <transition name="period-drop">
                <div v-if="trendCompareOpen" class="period-cal-panel" :style="trendCompareCalStyle" @click.stop>
                  <div class="period-calendar">
                    <div class="cal-month" v-for="(m, mi) in trendCompareMonths" :key="mi">
                      <div class="cal-month-head">
                        <button v-if="mi === 0" class="cal-nav" @click.stop="tcMonthOffset--">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m15 18-6-6 6-6"/></svg>
                        </button>
                        <span v-else class="cal-nav-spacer" />
                        <span class="cal-month-title">{{ m.label }}</span>
                        <button v-if="mi === 1" class="cal-nav" @click.stop="tcMonthOffset++">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m9 18 6-6-6-6"/></svg>
                        </button>
                        <span v-else class="cal-nav-spacer" />
                      </div>
                      <div class="cal-weekdays">
                        <span v-for="d in weekDays" :key="d" class="cal-wd">{{ d }}</span>
                      </div>
                      <div class="cal-grid">
                        <span
                          v-for="(day, di) in m.days"
                          :key="di"
                          :class="tcDayClass(day)"
                          @click.stop="pickTrendCompareDate(day)"
                        >{{ day ? day.label : '' }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </transition>
            </Teleport>
          </div>
        </div>

        <div class="card card-light blob-card">
          <div class="blob-bg" />
          <div class="blob-shape" />
          <div class="blob-content">
            <div class="metric-mode-label">{{ mediaCountLabel }} · {{ mediaTimeLabel }}</div>
            <div class="card-icon-wrap colored">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M13 8h2v12h-2zM9 4h2v16H9zm8 10h2v6h-2zM5 11h2v9H5z"/>
              </svg>
            </div>
            <h4>检测概览</h4>
            <p class="card-text">
              检测任务 <b>{{ dashboard.totals.totalTasks }}</b> 次<br/>
              处理图片 <b>{{ dashboard.totals.totalImages }}</b> 张<br/>
              发现缺陷 <b>{{ dashboard.totals.totalObjects }}</b> 处
            </p>
            <p class="card-text-sm">
              {{ dashboard.sceneDistribution.length }} 个场景<br/>
              {{ dashboard.classDistribution.length }} 种缺陷类别 <br/>
              平均 {{ Number(dashboard.totals.avgInferenceTimeMs || 0).toFixed(0) }}ms
            </p>
          </div>
        </div>
      </div>

      <EChartPanel :option="trendOption" :loading="loading" :empty="dashboard.dailyTrend.length === 0" height="260px" />

      <div class="side-right">
        <div class="card card-dark">
          <p class="card-eyebrow">主要指标</p>
          <h4>已完成检测任务</h4>
          <div class="progress-wrap">
            <div class="progress-row">
              <span class="progress-val">{{ dashboard.totals.totalTasks }}</span>
              <span class="progress-target">当前周期</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: dashboard.totals.totalTasks ? '100%' : '0%' }" />
            </div>
          </div>
        </div>
        <div class="kpi-fgrid">
          <div class="kpi-fcard">
            <div class="kpi-fhead">
              <span class="kpi-ficon green">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M21 16v-4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2zM13 6v4a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2z"/></svg>
              </span>
              <span class="kpi-ftitle">训练任务</span>
              <span :class="['kpi-fchg', kpiChanges.training >= 0 ? 'up' : 'down']">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path :d="kpiChanges.training >= 0 ? 'M12 8l-6 6h12z' : 'M12 16l6-6H6z'"/></svg>
                {{ kpiChangeLabel(kpiChanges.training) }}
              </span>
            </div>
            <div class="kpi-fbody">
              <p class="kpi-fval">{{ dashboard.totals.trainingTasks || 0 }}<small> 次</small></p>
              <div class="kpi-fbar"><div class="kpi-ffill" :style="{ width: Math.min((dashboard.totals.trainingTasks || 0) / Math.max(kpiMax, 1) * 100, 100) + '%' }" /></div>
            </div>
          </div>
          <div class="kpi-fcard">
            <div class="kpi-fhead">
              <span class="kpi-ficon blue">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
              </span>
              <span class="kpi-ftitle">检测图片</span>
              <span :class="['kpi-fchg', kpiChanges.images >= 0 ? 'up' : 'down']">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path :d="kpiChanges.images >= 0 ? 'M12 8l-6 6h12z' : 'M12 16l6-6H6z'"/></svg>
                {{ kpiChangeLabel(kpiChanges.images) }}
              </span>
            </div>
            <div class="kpi-fbody">
              <p class="kpi-fval">{{ dashboard.totals.totalImages }}<small> 张</small></p>
              <div class="kpi-fbar"><div class="kpi-ffill" :style="{ width: Math.min(dashboard.totals.totalImages / Math.max(kpiMax, 1) * 100, 100) + '%' }" /></div>
            </div>
          </div>
          <div class="kpi-fcard">
            <div class="kpi-fhead">
              <span class="kpi-ficon purple">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10" opacity="0.2"/><circle cx="12" cy="12" r="4"/></svg>
              </span>
              <span class="kpi-ftitle">缺陷目标</span>
              <span :class="['kpi-fchg', kpiChanges.objects >= 0 ? 'up' : 'down']">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path :d="kpiChanges.objects >= 0 ? 'M12 8l-6 6h12z' : 'M12 16l6-6H6z'"/></svg>
                {{ kpiChangeLabel(kpiChanges.objects) }}
              </span>
            </div>
            <div class="kpi-fbody">
              <p class="kpi-fval">{{ dashboard.totals.totalObjects }}<small> 处</small></p>
              <div class="kpi-fbar"><div class="kpi-ffill" :style="{ width: Math.min(dashboard.totals.totalObjects / Math.max(kpiMax, 1) * 100, 100) + '%' }" /></div>
            </div>
          </div>
          <div class="kpi-fcard">
            <div class="kpi-fhead">
              <span class="kpi-ficon orange">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
              </span>
              <span class="kpi-ftitle">平均耗时</span>
              <span :class="['kpi-fchg', kpiChanges.avgTime <= 0 ? 'up' : 'down']">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path :d="kpiChanges.avgTime <= 0 ? 'M12 8l-6 6h12z' : 'M12 16l6-6H6z'"/></svg>
                {{ kpiChangeLabel(Math.abs(kpiChanges.avgTime)) }}
              </span>
            </div>
            <div class="kpi-fbody">
              <p class="kpi-fval">{{ Number(dashboard.totals.avgInferenceTimeMs || 0).toFixed(0) }}<small> ms</small></p>
              <div class="kpi-fbar"><div class="kpi-ffill" :style="{ width: Math.min(Number(dashboard.totals.avgInferenceTimeMs || 0) / Math.max(kpiMaxTime, 1) * 100, 100) + '%' }" /></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- secondary charts -->
    <div class="dash-grid-bottom">
      <EChartPanel :title="text.classTitle" :option="classOption" :loading="loading" :empty="dashboard.classDistribution.length === 0" height="220px" />
      <EChartPanel title="每日训练趋势" :option="trainingTrendOption" :loading="loading" :empty="dashboard.trainingDailyTrend.length === 0" height="220px" />
      <EChartPanel :title="text.sceneTitle" :option="sceneOption" :loading="loading" :empty="dashboard.sceneDistribution.length === 0" height="220px" />
      <div class="card detect-time-card">
        <div class="dt-header">
          <span class="dt-title">检测耗时</span>
        </div>
        <div class="dt-range">
          <span class="dt-range-val">{{ dtMin }}-{{ dtMax }}</span>
          <span class="dt-range-unit">ms</span>
        </div>
        <div class="dt-date-row">
          <span class="dt-date">{{ dtDateLabel }}</span>
          <span class="dt-avg-label">Avg. {{ dtAvg }}</span>
        </div>
        <div class="dt-chart-wrap">
          <div class="dt-avg-line" />
          <div class="dt-chart">
            <div v-for="day in dtBars" :key="day.label" class="dt-bar-wrap">
              <div class="dt-bar-container">
                <div :class="['dt-bar', day.high ? 'high' : '']" :style="{ height: day.hPx + 'px' }">
                  <div v-if="day.dotTop" class="dt-dot top" />
                  <div v-if="day.dotBottom" class="dt-dot bottom" />
                </div>
              </div>
              <div class="dt-day">{{ day.label }}</div>
            </div>
          </div>
        </div>
        <div class="dt-readings">
          <div v-for="r in dtReadings" :key="r.label" class="dt-reading">
            <span class="dt-reading-time">{{ r.label }}</span>
            <span class="dt-reading-val">{{ r.value }}ms</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { exportStatisticsApi, getDashboardApi } from "@/api/statistics";
import { getScenesApi } from "@/api/models";
import { useUserStore } from '@/stores/user'
import EChartPanel from "@/components/charts/EChartPanel.vue";
import PageErrorAlert from "@/components/common/PageErrorAlert.vue";
import { getApiErrorMessage } from "@/utils/apiError";

function last30Days() {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 29)
  return [fmtDate(start), fmtDate(end)]
}
function fmtDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const loading = ref(false);
const settingsStore = useSettingsStore()
const userStore = useUserStore()
const router = useRouter()
const pageError = ref("");
const period = ref('30d');
const menuOpen = ref(false);
const periodRef = ref(null);
const filters = reactive({ dateRange: last30Days(), taskType: '', mediaType: '', sceneId: '', status: '', keyword: '', ownerUserId: '' });
const scenes = ref([])
const viewGranularity = ref('task')
const granularityOptions = [
  { value: 'task', label: 'Tasks' },
  { value: 'file', label: 'Files' },
  { value: 'frame', label: 'Frames' },
]
const taskTypeOptions = [
  { value: 'single', label: 'Single' }, { value: 'batch', label: 'Batch' },
  { value: 'zip', label: 'ZIP' }, { value: 'video', label: 'Video' }, { value: 'camera', label: 'Camera' },
]
const mediaTypeOptions = [
  { value: '', label: '全部' }, { value: 'image', label: '图片' }, { value: 'video', label: '视频' },
]
const mediaCountLabel = computed(() => filters.mediaType === 'video' ? '检测帧数' : filters.mediaType === 'image' ? '检测图片' : '处理媒体量')
const mediaTimeLabel = computed(() => filters.mediaType === 'video' ? '单帧平均耗时' : '单图平均耗时')
function formatDashboardDuration(value) {
  const ms = Number(value || 0)
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}
const statusOptions = [
  { value: 'pending', label: 'Pending' }, { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' }, { value: 'failed', label: 'Failed' },
]

const periodOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天', value: '30d' },
  { label: '本月', value: 'month' },
  { label: '自定义', value: 'custom' },
]

const currentPeriodLabel = computed(() => {
  const found = periodOptions.find(o => o.value === period.value)
  return found ? found.label : '近 30 天'
})

const dropStyle = computed(() => {
  if (!periodRef.value) return {}
  const r = periodRef.value.getBoundingClientRect()
  return { position: 'fixed', top: r.bottom + 6 + 'px', left: r.left + 'px', minWidth: r.width + 'px' }
})

// Calendar panel to the left of the dropdown
const calPanelStyle = computed(() => {
  if (!periodRef.value) return {}
  const r = periodRef.value.getBoundingClientRect()
  return { position: 'fixed', top: r.bottom + 6 + 'px', right: window.innerWidth - r.left + 10 + 'px' }
})

function closeMenu() {
  if (period.value !== 'custom') {
    menuOpen.value = false
  }
}

function selectPeriod(val) {
  if (val === 'custom') {
    period.value = 'custom'
    // restore previous selection
    calSelStart.value = filters.dateRange[0] || null
    calSelEnd.value = filters.dateRange[1] || null
    return
  }
  period.value = val
  menuOpen.value = false
  prevDateOverride.value = null
  if (val === '7d') {
    const end = new Date(); const start = new Date()
    start.setDate(start.getDate() - 6)
    filters.dateRange = [fmtDate(start), fmtDate(end)]
  } else if (val === '30d') {
    filters.dateRange = last30Days()
  } else if (val === 'month') {
    const now = new Date()
    const start = new Date(now.getFullYear(), now.getMonth(), 1)
    filters.dateRange = [fmtDate(start), fmtDate(now)]
  }
  loadDashboard()
}

function onCustomDateChange() {
  menuOpen.value = false
  loadDashboard()
}

// ── custom calendar ──
const calMonthOffset = ref(-1)
const calSelStart = ref(null)
const calSelEnd = ref(null)

const weekDays = ['日', '一', '二', '三', '四', '五', '六']

const calendarMonths = computed(() => {
  const ms = []
  for (let i = 0; i < 2; i++) {
    const now = new Date()
    const ym = new Date(now.getFullYear(), now.getMonth() + calMonthOffset.value + i, 1)
    const year = ym.getFullYear()
    const month = ym.getMonth()
    const firstDow = new Date(year, month, 1).getDay()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const days = []
    for (let d = 0; d < firstDow; d++) days.push(null)
    for (let d = 1; d <= daysInMonth; d++) {
      days.push({ label: d, date: fmtDate(new Date(year, month, d)) })
    }
    ms.push({ label: `${year}年${month + 1}月`, days })
  }
  return ms
})

function calDayClass(day) {
  if (!day) return 'cal-day-empty'
  const d = day.date
  const s = calSelStart.value
  const e = calSelEnd.value
  const today = fmtDate(new Date())
  const cls = ['cal-day']
  if (d > today) cls.push('future')
  if (d === s || d === e) cls.push('active')
  else if (s && e && d > s && d < e) cls.push('in-range')
  return cls.join(' ')
}

function pickDate(day) {
  if (!day || day.date > fmtDate(new Date())) return
  if (!calSelStart.value || (calSelStart.value && calSelEnd.value)) {
    calSelStart.value = day.date
    calSelEnd.value = null
    return
  }
  if (day.date < calSelStart.value) {
    calSelStart.value = day.date
    calSelEnd.value = null
    return
  }
  calSelEnd.value = day.date
  filters.dateRange = [calSelStart.value, calSelEnd.value]
  prevDateOverride.value = null
  menuOpen.value = false
  period.value = 'custom'
  loadDashboard()
  // Keep selection visible briefly, then reset
  setTimeout(() => { calSelStart.value = null; calSelEnd.value = null }, 200)
}

function onClickOutside(e) {
  if (periodRef.value && !periodRef.value.contains(e.target)) {
    menuOpen.value = false
  }
}
onMounted(() => {
  document.addEventListener('click', onClickOutside)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
})
const dashboard = reactive({
  totals: { totalTasks: 0, totalImages: 0, totalObjects: 0, avgInferenceTimeMs: 0, trainingTasks: 0 },
  classDistribution: [],
  dailyTrend: [],
  dailyInferenceTime: [],
  trainingDailyTrend: [],
  sceneDistribution: [],
  updatedAt: "",
});
const axisStyle = { axisLine: { lineStyle: { color: "#d0d5dd" } }, axisLabel: { color: "#667085" } };

const trendTotal = computed(() => {
  return dashboard.dailyTrend.reduce((s, d) => s + (d.tasks || 0), 0)
})

const trendPrevTotal = computed(() => {
  return prevDashboard.dailyTrend.reduce((s, d) => s + (d.tasks || 0), 0) || 0
})

const trendChange = computed(() => {
  if (!trendPrevTotal.value) return 0
  return Math.round(((trendTotal.value - trendPrevTotal.value) / trendPrevTotal.value) * 100)
})

const trendChangeText = computed(() => {
  const pct = trendChange.value
  if (pct > 0) return `↑${pct}%`
  if (pct < 0) return `↓${Math.abs(pct)}%`
  return '0%'
})

const prevDateOverride = ref(null) // null = auto-compute

const trendPrevRange = computed(() => {
  if (prevDateOverride.value) return { start: prevDateOverride.value.start, end: prevDateOverride.value.end }
  const [s, e] = filters.dateRange
  if (!s || !e) return { start: '', end: '' }
  const start = new Date(s)
  const end = new Date(e)
  const days = Math.round((end - start) / (1000 * 60 * 60 * 24))
  const prevEnd = new Date(start)
  prevEnd.setDate(prevEnd.getDate() - 1)
  const prevStart = new Date(prevEnd)
  prevStart.setDate(prevStart.getDate() - days)
  return { start: fmtDate(prevStart), end: fmtDate(prevEnd) }
})

const trendDateLabel = computed(() => {
  const { start, end } = trendPrevRange.value
  if (start && end) return `${start} — ${end}`
  return '选择日期范围'
})

const trendCompareOpen = ref(false)
const trendCompareRef = ref(null)
const tcMonthOffset = ref(-1)
const tcSelStart = ref(null)
const tcSelEnd = ref(null)

const trendCompareCalStyle = computed(() => {
  if (!trendCompareRef.value) return {}
  const r = trendCompareRef.value.getBoundingClientRect()
  return { position: 'fixed', top: r.bottom + 6 + 'px', left: r.left + 'px' }
})

const trendCompareMonths = computed(() => {
  const ms = []
  for (let i = 0; i < 2; i++) {
    const now = new Date()
    const ym = new Date(now.getFullYear(), now.getMonth() + tcMonthOffset.value + i, 1)
    const year = ym.getFullYear()
    const month = ym.getMonth()
    const firstDow = new Date(year, month, 1).getDay()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const days = []
    for (let d = 0; d < firstDow; d++) days.push(null)
    for (let d = 1; d <= daysInMonth; d++) {
      days.push({ label: d, date: fmtDate(new Date(year, month, d)) })
    }
    ms.push({ label: `${year}年${month + 1}月`, days })
  }
  return ms
})

function tcDayClass(day) {
  if (!day) return 'cal-day-empty'
  const d = day.date
  const s = tcSelStart.value
  const e = tcSelEnd.value
  const today = fmtDate(new Date())
  const cls = ['cal-day']
  if (d > today) cls.push('future')
  if (d === s || d === e) cls.push('active')
  else if (s && e && d > s && d < e) cls.push('in-range')
  return cls.join(' ')
}

function pickTrendCompareDate(day) {
  if (!day || day.date > fmtDate(new Date())) return
  if (!tcSelStart.value || (tcSelStart.value && tcSelEnd.value)) {
    tcSelStart.value = day.date
    tcSelEnd.value = null
    return
  }
  if (day.date < tcSelStart.value) {
    tcSelStart.value = day.date
    tcSelEnd.value = null
    return
  }
  tcSelEnd.value = day.date
  prevDateOverride.value = { start: tcSelStart.value, end: tcSelEnd.value }
  trendCompareOpen.value = false
  tcSelStart.value = null
  tcSelEnd.value = null
  loadDashboard()
}

function toggleTrendCompareCal() {
  trendCompareOpen.value = !trendCompareOpen.value
  if (trendCompareOpen.value) {
    const { start, end } = trendPrevRange.value
    tcSelStart.value = start || null
    tcSelEnd.value = end || null
    // Show the end date's month on the right panel
    if (end) {
      const endDate = new Date(end)
      const now = new Date()
      tcMonthOffset.value = (endDate.getFullYear() - now.getFullYear()) * 12 + (endDate.getMonth() - now.getMonth()) - 1
    } else {
      tcMonthOffset.value = -1
    }
  }
}

function openTrendDatePicker() {
  period.value = 'custom'
  menuOpen.value = true
  calMonthOffset.value = -1
  calSelStart.value = filters.dateRange[0] || null
  calSelEnd.value = filters.dateRange[1] || null
}

const prevDashboard = reactive({
  totals: { totalTasks: 0, totalImages: 0, totalObjects: 0, avgInferenceTimeMs: 0, trainingTasks: 0 },
})

const kpiChanges = computed(() => {
  const curr = dashboard.totals
  const prev = prevDashboard.totals
  const pct = (a, b) => b ? Math.round((a - b) / b * 100) : 0
  return {
    training: pct(curr.trainingTasks || 0, prev.trainingTasks || 0),
    images: pct(curr.totalImages, prev.totalImages),
    objects: pct(curr.totalObjects, prev.totalObjects),
    avgTime: pct(curr.avgInferenceTimeMs, prev.avgInferenceTimeMs),
  }
})

const kpiChangeLabel = (val) => {
  if (val > 0) return `↑${val}%`
  if (val < 0) return `↓${Math.abs(val)}%`
  return '0%'
}

const kpiMax = computed(() => Math.max(
  dashboard.totals.trainingTasks || 0,
  dashboard.totals.totalImages || 0,
  dashboard.totals.totalObjects || 0,
  1,
))

const kpiMaxTime = computed(() => Math.max(Number(dashboard.totals.avgInferenceTimeMs || 0), 1))

const text = computed(() => settingsStore.isEnglish ? {
  refresh: 'Refresh',
  reload: 'Reload',
  startDate: 'Start date',
  endDate: 'End date',
  trendTitle: 'Daily Detection Trend',
  trendSubtitle: 'Task count by creation date',
  classTitle: 'Defect Class Distribution',
  classSubtitle: 'Target counts in historical results',
  sceneTitle: 'Detection Scene Distribution',
  sceneSubtitle: 'Completed tasks by scene',
  taskSeries: 'Detection tasks',
  objectUnit: 'defects',
   loadFailed: 'Failed to load dashboard data',
   keyword: 'Task, scene or file keyword',
   allTypes: 'All task types',
   mediaType: 'Media type',
   allScenes: 'All scenes',
   allStatuses: 'All statuses',
   userId: 'Admin user ID',
  applyFilters: 'Apply',
  viewGranularity: 'View granularity',
  openView: 'Open filtered view',
 } : {
  keyword: '关键词',
  allTypes: '全部任务类型',
  mediaType: '媒体类型',
  allScenes: '全部场景',
  allStatuses: '全部状态',
  userId: '管理员用户 ID',
  applyFilters: '筛选',
  refresh: '刷新',
  reload: '重新加载',
  startDate: '开始日期',
  endDate: '结束日期',
  trendTitle: '每日检测任务趋势',
  trendSubtitle: '按创建日期统计检测任务数量',
  classTitle: '缺陷类别分布',
  classSubtitle: '当前账号历史结果中的目标数量',
  sceneTitle: '检测场景分布',
  sceneSubtitle: '已完成任务在各检测场景中的数量',
  taskSeries: '检测任务',
  objectUnit: '处',
  loadFailed: '看板数据加载失败',
})

const trendOption = computed(() => ({
  tooltip: { trigger: "axis" },
  color: ["#2563eb", "#a1a1aa"],
  grid: { left: 48, right: 16, top: 16, bottom: 28 },
  xAxis: { type: "category", data: dashboard.dailyTrend.map((item) => item.date), ...axisStyle },
  yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#edf0f5" } }, ...axisStyle },
  series: [
    { name: text.value.taskSeries, type: "line", smooth: true, symbolSize: 0, areaStyle: { color: "rgba(37,99,235,.06)" }, data: dashboard.dailyTrend.map((item) => item.tasks) },
    { name: "上一周期", type: "line", smooth: true, symbolSize: 0, lineStyle: { color: "#a1a1aa" }, itemStyle: { color: "#a1a1aa" }, data: prevDashboard.dailyTrend.map((item) => item.tasks) },
  ],
}));

const classOption = computed(() => ({
  tooltip: { trigger: "item", formatter: `{b}<br/>{c} ${text.value.objectUnit} · {d}%` },
  color: ["#2563eb", "#7c3aed", "#06b6d4", "#10b981", "#f59e0b", "#f97316"],
  legend: { type: "scroll", orient: "vertical", right: 4, top: "middle" },
  series: [{ type: "pie", radius: ["43%", "70%"], center: ["38%", "53%"], avoidLabelOverlap: true, itemStyle: { borderColor: "#fff", borderWidth: 3 }, label: { show: false }, emphasis: { label: { show: true, fontSize: 15, fontWeight: "bold" } }, data: dashboard.classDistribution }],
}));

const trainingTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  color: ['#0ea5e9'],
  grid: { left: 48, right: 16, top: 16, bottom: 28 },
  xAxis: { type: 'category', data: dashboard.trainingDailyTrend.map((item) => item.date), ...axisStyle },
  yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#edf0f5' } }, ...axisStyle },
  series: [{ name: '训练任务', type: 'bar', data: dashboard.trainingDailyTrend.map((item) => item.tasks) }],
}));

// Detection time bar chart data (real per-day inference time from DB)
const dtBars = computed(() => {
  const data = dashboard.dailyInferenceTime?.length ? dashboard.dailyInferenceTime : []
  if (!data.length) return []
  const globalMax = Math.max(...data.map(d => d.max || 0), 1)
  return data.slice(-7).map((d, i) => ({
    label: ['日','一','二','三','四','五','六'][new Date(d.date + 'T00:00:00').getDay()] || d.date.slice(5),
    min: d.min || 0,
    max: d.max || 0,
    avg: d.avg || 0,
    hPx: Math.max(8, ((d.max || 0) / globalMax) * 50),
    high: (d.max || 0) >= globalMax * 0.7,
    dotTop: i === 1 || i === 6,
    dotBottom: i === 2 || i === 4,
    date: d.date,
  }))
})

const dtMin = computed(() => {
  const active = dtBars.value.filter(d => d.max > 0 || d.avg > 0 || d.min > 0)
  return active.length ? Math.round(Math.min(...active.map(d => d.min))) : 0
})
const dtMax = computed(() => Math.round(Math.max(...dtBars.value.map(d => d.max), 0)))
const dtAvg = computed(() => {
  if (!dtBars.value.length) return 0
  const active = dtBars.value.filter(d => d.max > 0 || d.avg > 0 || d.min > 0)
  return active.length ? Math.round(active.reduce((s, d) => s + d.avg, 0) / active.length) : 0
})
const dtDateLabel = computed(() => {
  const bars = dtBars.value
  if (!bars.length) return ''
  return `${bars[0].date} — ${bars[bars.length - 1].date}`
})

const dtReadings = computed(() => {
  if (!dtBars.value.length) return []
  return dtBars.value.slice(-2).map(d => ({
    label: d.date,
    value: Math.round(d.avg || 0),
  }))
})
const sceneOption = computed(() => ({
  tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
  color: ["#B8F7B7"],
  grid: { left: 110, right: 20, top: 12, bottom: 24 },
  xAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#edf0f5" } }, ...axisStyle },
  yAxis: { type: "category", data: dashboard.sceneDistribution.map((item) => item.name), ...axisStyle },
  series: [{ type: "bar", barMaxWidth: 32, data: dashboard.sceneDistribution.map((item) => item.value), itemStyle: { borderRadius: [0, 6, 6, 0] } }],
}));

async function loadDashboard() {
  loading.value = true;
  pageError.value = "";
  try {
    const data = await getDashboardApi({
      startDate: filters.dateRange?.[0],
      endDate: filters.dateRange?.[1],
      taskType: filters.taskType,
      mediaType: filters.mediaType,
      sceneId: filters.sceneId,
      status: filters.status,
      keyword: filters.keyword,
      userId: filters.ownerUserId,
    });
    Object.assign(dashboard, data);
    // Fetch previous period for comparison
    const { start: ps, end: pe } = trendPrevRange.value
    if (ps && pe) {
      try {
        const prevData = await getDashboardApi({ startDate: ps, endDate: pe, ...filters })
        Object.assign(prevDashboard, prevData)
      } catch { /* prev period data is best-effort */ }
    } else {
      prevDashboard.totals = { totalTasks: 0, totalImages: 0, totalObjects: 0, avgInferenceTimeMs: 0, trainingTasks: 0 }
      prevDashboard.dailyTrend = []
    }
  } catch (error) {
    pageError.value = getApiErrorMessage(error, text.value.loadFailed);
  } finally {
    loading.value = false;
  }
}

function openFilteredHistory() {
  router.push({ name: 'History', query: {
    scene_id: filters.sceneId || undefined,
    task_type: filters.taskType || undefined,
    status: filters.status || undefined,
    media_type: viewGranularity.value === 'frame' ? 'frame' : (filters.mediaType || undefined),
    keyword: filters.keyword || undefined,
    owner_user_id: filters.ownerUserId || undefined,
  } })
}

async function exportDashboard() {
  try {
    const blob = await exportStatisticsApi({ days: period.value === '7d' ? 7 : 30, sceneId: filters.sceneId, taskType: filters.taskType, mediaType: filters.mediaType, status: filters.status, keyword: filters.keyword, ownerUserId: filters.ownerUserId, startDate: filters.dateRange?.[0], endDate: filters.dateRange?.[1] })
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'detection-statistics.csv'; link.click(); URL.revokeObjectURL(url)
  } catch (error) { pageError.value = getApiErrorMessage(error, text.value.loadFailed) }
}

onMounted(() => {
  getScenesApi().then((items) => { scenes.value = items || [] }).catch(() => {})
  loadDashboard()
});
</script>

<style lang="scss" scoped>
.dashboard-page {
  padding: 0px 0px 0px;
  max-width: 1200px;
  margin: 0 auto;
}

.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.metric-mode-label { margin-bottom: 8px; color: var(--app-text-secondary); font-size: 12px; }
.dashboard-filter-bar {
  display: grid;
  grid-template-columns: minmax(180px, 1.5fr) repeat(5, minmax(120px, 1fr)) auto;
  gap: 8px;
  margin-bottom: 12px;
  align-items: center;
}
.format-select { width: 112px; }

.dash-title {
  font-size: 40px;
  font-weight: 600;
  color: #000000;
  letter-spacing: -0.3px;
}

.dash-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.period-wrap {
  position: relative;
}

.period-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid #d4d4d8;
  border-radius: 8px;
  background: #fff;
  color: #18181b;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s;

  &:hover { border-color: #a1a1aa; }
}

.period-label {
  color: #71717a;
  font-weight: 400;

  &::after { content: ''; }
}

.period-val {
  font-weight: 500;
}

.refresh-btn {
  .spin {
    animation: dash-spin 1s linear infinite;
  }
}

@keyframes dash-spin {
  to { transform: rotate(360deg); }
}

/* dropdown */
.period-overlay {
  position: fixed;
  inset: 0;
  z-index: 2999;
}

.period-dropdown {
  z-index: 3000;
  min-width: 170px;
  background: #fff;
  border: 1px solid #e4e4e7;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08), 0 8px 32px rgba(0,0,0,0.06);
  padding: 8px;
  display: flex;
  flex-direction: column;
}

.period-item {
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  color: #18181b;
  cursor: pointer;
  transition: background 0.15s;

  &:hover { background: #f5f5f5; }

  &.active {
    background: #f5f5f5;
    font-weight: 600;
  }
}

.period-divider {
  height: 1px;
  background: #e4e4e7;
  margin: 6px 0;
}

.period-cal-panel {
  z-index: 3000;
  background: #fff;
  border: 1px solid #e4e4e7;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08), 0 8px 32px rgba(0,0,0,0.06);
}

.period-calendar {
  display: flex;
  gap: 32px;
  padding: 8px 16px 4px;
}

.cal-month {
  flex: 1;
  min-width: 196px;
}

.cal-month-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  height: 28px;
}

.cal-nav {
  width: 28px; height: 28px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #52525b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover { background: #f4f4f5; }
}

.cal-nav-spacer {
  width: 28px; height: 28px;
}

.cal-month-title {
  font-size: 14px;
  font-weight: 600;
  color: #18181b;
}

.cal-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  text-align: center;
  margin-bottom: 4px;
}

.cal-wd {
  font-size: 12px;
  color: #a1a1aa;
  padding: 6px 0;
  font-weight: 500;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  text-align: center;
}

.cal-day {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  width: 32px;
  justify-self: center;
  border-radius: 50%;
  font-size: 13px;
  color: #18181b;
  cursor: pointer;
  transition: background 0.12s;

  &:hover { background: #f4f4f5; }

  &.future {
    color: #d4d4d8;
    cursor: default;
    pointer-events: none;
  }

  &.active {
    background: #18181b;
    color: #fff;
    font-weight: 600;
  }

  &.in-range {
    background: #f5f5f5;
    border-radius: 0;
  }
}

.cal-day-empty {
  height: 32px;
}

.period-drop-enter-active { transition: all 0.15s ease-out; }
.period-drop-leave-active { transition: all 0.1s ease-in; }
.period-drop-enter-from { opacity: 0; transform: translateY(-4px); }
.period-drop-leave-to { opacity: 0; transform: translateY(-2px); }

/* cards */
.card {
  background: #fff;
  border: 1px solid #e7ebf1;
  border-radius: 16px;
  padding: 12px 16px;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -2px rgba(0,0,0,0.03);
}

.card-head {
  margin-bottom: 4px;

  h3 {
    margin: 0 0 2px;
    font-size: 16px;
    font-weight: 700;
    color: #18181b;
  }
}

.card-sub {
  font-size: 12px;
  color: #a1a1aa;
}

/* top row: metric header + sidebar */
.dash-top-row {
  display: grid;
  grid-template-columns: 190px 1fr 280px;
  gap: 12px;
  margin-bottom: 16px;
  align-items: stretch;

  :deep(.chart-panel) {
    border-radius: 16px;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -2px rgba(0,0,0,0.03);
  }
}

.chart-metric-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-self: start;
  padding-top: 13px;
}

.chart-metric-label {
  font-size: 16px;
  font-weight: 700;
  color: #18181b;
  margin-bottom: 4px;
}

.chart-metric-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.chart-metric-value {
  font-size: 32px;
  font-weight: 700;
  color: #18181b;
  letter-spacing: -0.5px;
  line-height: 1;
}

.chart-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;

  &.blue {
    background: #2563eb;
    color: #fff;
  }

  &.blue-light {
    background: #2563eb;
    color: #fff;
  }
}

.chart-compare-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chart-compare-label {
  font-size: 12px;
  color: #a1a1aa;
}

.chart-compare-date {
  font-size: 12px;
  color: #52525b;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;

  &:hover { color: #18181b; }
}

.cal-arrow {
  flex-shrink: 0;
}

.side-left {
  display: flex;
  flex-direction: column;
  gap: 25px;
  max-width: 190px;
  height: 100%;

  .card-light {
    margin-top: auto;
  }
}

.side-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* sidebar */
.side-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card-dark {
  background: #18181b;
  color: #fff;
  border-color: #18181b;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
  padding: 12px 16px;
  justify-content: space-between;

  .card-eyebrow {
    margin: 0 0 2px;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #71717a;
  }

  h4 {
    margin: 0 0 4px;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }
}

.progress-wrap {
}

.progress-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 4px;
}

.progress-val {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -1px;
}

.progress-target {
  font-size: 10px;
  color: #a1a1aa;
}

.progress-bar {
  width: 100%;
  height: 4px;
  background: #3f3f46;
  border-radius: 10px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #fff;
  border-radius: 10px;
  transition: width 0.6s ease;
}

.card-light {
  justify-content: space-between;

  .card-icon-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 7px;
    background: #f4f4f5;
    border: 1px solid #e4e4e7;
    color: #18181b;
    margin-bottom: 6px;

    &.plain {
      background: transparent;
      border: 0;
      justify-content: flex-start;
      padding-left: 0;
    }

    &.colored {
      width: 24px;
      height: 24px;
      border-radius: 999px;
      background: #ff0000;
      border: 0;
      color: #fff;
    }
  }

  h4 {
    margin: 0 0 4px;
    font-size: 14px;
    font-weight: 700;
    color: #18181b;
  }
}

.card-text {
  margin: 0;
  font-size: 12px;
  color: #71717a;
  line-height: 1.4;

  b {
    color: #18181b;
    font-weight: 600;
  }
}

.card-text-sm {
  margin: 6px 0 0;
  font-size: 11px;
  color: #a1a1aa;
  line-height: 1.4;
}

/* KPI 2x2 grid */
.side-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}

.kpi-fgrid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: auto;
}

.kpi-fcard {
  padding: 12px;
  background: #fff;
  border-radius: 16px;
  border: 1px solid #e7ebf1;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -2px rgba(0,0,0,0.03);
}

.kpi-fhead {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kpi-ficon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px; height: 20px;
  border-radius: 999px;
  color: #fff;
  flex-shrink: 0;

  &.green { background: #10b981; }
  &.blue { background: #3b82f6; }
  &.purple { background: #8b5cf6; }
  &.orange { background: #f59e0b; }
}

.kpi-ftitle {
  font-size: 12px;
  color: #374151;
  font-weight: 500;
}

.kpi-fchg {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  display: flex;
  align-items: center;

  &.up { color: #059669; }
  &.down { color: #dc2626; }
}

.kpi-fbody {
  margin-top: 8px;
}

.kpi-fval {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.1;

  small {
    font-size: 11px;
    font-weight: 500;
    color: #9ca3af;
    margin-left: 2px;
  }
}

.kpi-fbar {
  width: 100%;
  height: 5px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.kpi-ffill {
  height: 100%;
  background: #10b981;
  border-radius: 3px;
  transition: width 0.5s ease;
}

/* bottom charts row */
.dash-grid-bottom {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 0;

  :deep(.chart-panel) {
    border-radius: 16px;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -2px rgba(0,0,0,0.03);
  }
}

/* secondary charts */
.dash-grid-secondary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

/* blob card */
.blob-card {
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid #e7ebf1;
  box-shadow: none;
  background: #fff;
}
.blob-card .blob-shape { display: none; }

.blob-bg {
  position: absolute;
  inset: 4px;
  z-index: 2;
  background: rgba(255, 255, 255, .95);
  backdrop-filter: blur(24px);
  border-radius: 12px;
}

.blob-shape {
  position: absolute;
  z-index: 1;
  top: 50%;
  left: 50%;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background-color: #ff0000;
  opacity: 1;
  filter: blur(12px);
  animation: blob-bounce 5s infinite ease;
}

.blob-content {
  position: relative;
  z-index: 3;
}

@keyframes blob-bounce {
  0%   { transform: translate(-100%, -100%) translate3d(0, 0, 0); }
  25%  { transform: translate(-100%, -100%) translate3d(100%, 0, 0); }
  50%  { transform: translate(-100%, -100%) translate3d(100%, 100%, 0); }
  75%  { transform: translate(-100%, -100%) translate3d(0, 100%, 0); }
  100% { transform: translate(-100%, -100%) translate3d(0, 0, 0); }
}

/* detection time card */
.detect-time-card {
  padding: 16px 18px;
}

.dt-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.dt-title {
  font-size: 16px;
  font-weight: 700;
  color: #1a1a1a;
}

.dt-range {
  margin-bottom: 2px;
}

.dt-range-val {
  font-size: 28px;
  font-weight: 700;
  color: #1a1a1a;
  letter-spacing: -0.5px;
}

.dt-range-unit {
  font-size: 24px;
  font-weight: 300;
  color: #b0b0b0;
  margin-left: 4px;
}

.dt-date-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.dt-date {
  font-size: 11px;
  color: #999;
}

.dt-chart-wrap {
  position: relative;
  height: 80px;
  margin-bottom: 16px;
}

.dt-avg-line {
  position: absolute;
  left: 0; right: 0;
  top: 45%;
  height: 1.5px;
  background: #e0e0e0;
}

.dt-avg-label {
  background: #1a1a1a;
  color: #fff;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}

.dt-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 100%;
  padding: 0 10px;
}

.dt-bar-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.dt-bar-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.dt-bar {
  width: 16px;
  background: linear-gradient(to bottom, #ff5a76, #ff8fa3);
  border-radius: 8px;
  position: relative;
  transition: height 0.3s ease;
  min-height: 4px;

  &:hover { transform: scale(1.05); }

  &.high {
    background: linear-gradient(to bottom, #ff2d55, #ff5a76);
  }
}

.dt-dot {
  width: 7px;
  height: 7px;
  background: #fff;
  border: 1.5px solid #ff5a76;
  border-radius: 50%;
  position: absolute;
  left: 50%;
  transform: translateX(-50%);

  &.top { top: -4px; }
  &.bottom { bottom: -4px; }
}

.dt-day {
  font-size: 9px;
  color: #999;
  font-weight: 500;
}

.dt-readings {
  border-top: 1.5px solid #f0f0f0;
  padding-top: 10px;
}

.dt-reading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1.5px solid #f0f0f0;

  &:last-child { border-bottom: none; }
}

.dt-reading-time {
  font-size: 10px;
  color: #999;
}

.dt-reading-val {
  font-size: 12px;
  font-weight: 700;
  color: #1a1a1a;
}

@media (max-width: 980px) {
  .dashboard-filter-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dash-top-row {
    grid-template-columns: 1fr;
  }
  .dash-grid-bottom,
  .dash-grid-secondary {
    grid-template-columns: 1fr;
  }
}
</style>
