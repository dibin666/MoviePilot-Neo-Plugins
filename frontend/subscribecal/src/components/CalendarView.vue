<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import DayEventsDialog from './cards/DayEventsDialog.vue'
import EventRow from './cards/EventRow.vue'
import type { TimeLineItem } from '../types'
import {
  addDays,
  compareItems,
  ensureImageSettings,
  formatDateLabel,
  formatEpisode,
  formatTimeRange,
  getDaypartColor,
  getErrorMessage,
  getImageUrl,
  normalizeItems,
  openMediaDetail,
  PLUGIN_ID,
  startOfToday,
  toDateKey,
} from '../utils/calendar'
import { buildSubscribeUrl, copyText, downloadIcs, loadSystemEnv, useHostToast } from '../utils/actions'

const props = defineProps({
  api: {
    type: Object,
    required: true,
  },
  // 是否嵌入在插件详情弹窗中
  embedded: {
    type: Boolean,
    default: false,
  },
  // 是否显示“插件配置”按钮
  showSwitch: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['close', 'switch'])

const toast = useHostToast()

const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日']
const TYPE_FILTERS = [
  { value: 'all', title: '全部', icon: 'mdi-view-grid-outline' },
  { value: '电视剧', title: '剧集', icon: 'mdi-television-play' },
  { value: '电影', title: '电影', icon: 'mdi-filmstrip' },
]
const LEGENDS = [
  { color: 'warning', text: '上午' },
  { color: 'info', text: '下午' },
  { color: 'primary', text: '晚间' },
  { color: '#3949AB', text: '深夜' },
  { color: 'secondary', text: '时间待定' },
]

// 当前月份（1 号）
const today = ref(startOfToday())
const cursor = ref(new Date(today.value.getFullYear(), today.value.getMonth(), 1))
const typeFilter = ref<string>('all')
const hideObtained = ref(false)

const items = ref<TimeLineItem[]>([])
const loading = ref(false)
const loadError = ref('')
const refreshing = ref(false)

// 屏幕宽度，窄屏使用列表视图
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const compact = computed(() => viewportWidth.value < 760)

const dialog = reactive({
  show: false,
  date: '',
  items: [] as TimeLineItem[],
})

let requestId = 0
let refreshTimers: ReturnType<typeof setTimeout>[] = []

const monthLabel = computed(() => `${cursor.value.getFullYear()}年${cursor.value.getMonth() + 1}月`)


// 月历网格：周一为每周第一天
const gridRange = computed(() => {
  const first = cursor.value
  const offset = (first.getDay() + 6) % 7
  const start = addDays(first, -offset)
  const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  const weeks = Math.ceil((offset + daysInMonth) / 7)
  return { start, end: addDays(start, weeks * 7 - 1), weeks }
})

const filteredItems = computed(() =>
  items.value.filter(item => {
    if (typeFilter.value !== 'all' && item.type !== typeFilter.value) return false
    if (hideObtained.value && item.downloaded) return false
    return true
  }),
)

const itemsByDate = computed(() => {
  const map = new Map<string, TimeLineItem[]>()
  for (const item of filteredItems.value) {
    if (!map.has(item.date)) map.set(item.date, [])
    map.get(item.date)!.push(item)
  }
  map.forEach(list => list.sort(compareItems))
  return map
})

const weeks = computed(() => {
  const result: { key: string; days: { key: string; day: number; inMonth: boolean; isToday: boolean; isPast: boolean; weekend: boolean; items: TimeLineItem[] }[] }[] = []
  const todayKey = toDateKey(today.value)
  const month = cursor.value.getMonth()
  for (let w = 0; w < gridRange.value.weeks; w++) {
    const days = []
    for (let d = 0; d < 7; d++) {
      const date = addDays(gridRange.value.start, w * 7 + d)
      const key = toDateKey(date)
      days.push({
        key,
        day: date.getDate(),
        inMonth: date.getMonth() === month,
        isToday: key === todayKey,
        isPast: key < todayKey,
        weekend: d >= 5,
        items: itemsByDate.value.get(key) ?? [],
      })
    }
    result.push({ key: days[0].key, days })
  }
  return result
})

// 窄屏列表：本月有播出的日期
const agendaDays = computed(() => {
  const month = cursor.value.getMonth()
  return Array.from(itemsByDate.value.entries())
    .filter(([key]) => Number(key.slice(5, 7)) - 1 === month)
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([key, list]) => ({ key, items: list }))
})

// 本月统计
const stats = computed(() => {
  const month = cursor.value.getMonth()
  const monthItems = filteredItems.value.filter(item => Number(item.date.slice(5, 7)) - 1 === month)
  const todayKey = toDateKey(today.value)
  return {
    total: monthItems.length,
    shows: new Set(monthItems.map(item => item.id)).size,
    today: (itemsByDate.value.get(todayKey) ?? []).length,
    upcoming: monthItems.filter(item => item.date >= todayKey).length,
  }
})

async function loadEvents() {
  const current = ++requestId
  loading.value = true
  loadError.value = ''
  try {
    const response = await props.api.get(`plugin/${PLUGIN_ID}/events`, {
      params: { start: toDateKey(gridRange.value.start), end: toDateKey(gridRange.value.end) },
    })
    if (current !== requestId) return
    items.value = normalizeItems(response)
  } catch (error) {
    if (current !== requestId) return
    console.error(error)
    loadError.value = getErrorMessage(error, '日历数据加载失败')
  } finally {
    if (current === requestId) loading.value = false
  }
}

function shiftMonth(delta: number) {
  cursor.value = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + delta, 1)
}

function goToday() {
  today.value = startOfToday()
  cursor.value = new Date(today.value.getFullYear(), today.value.getMonth(), 1)
}

function openDay(key: string, list: TimeLineItem[]) {
  dialog.date = key
  dialog.items = list
  dialog.show = true
}

function handleOpenMedia(item: TimeLineItem) {
  dialog.show = false
  if (props.embedded) emit('close')
  openMediaDetail(item)
}

function cellTitle(item: TimeLineItem): string {
  const episode = formatEpisode(item)
  return [item.name || item.summary, episode, item.episode_name, formatTimeRange(item)].filter(Boolean).join(' · ')
}

function clearRefreshTimers() {
  refreshTimers.forEach(timer => clearTimeout(timer))
  refreshTimers = []
}

async function refreshData() {
  refreshing.value = true
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/refresh`)
    if (result?.success === false) {
      toast.error(result?.message || '刷新失败')
      return
    }
    toast.info(result?.message || '已开始刷新日历数据')
    clearRefreshTimers()
    // 刷新在后台进行，分几次拉取最新结果
    refreshTimers = [5000, 15000, 40000].map(delay => setTimeout(() => void loadEvents(), delay))
  } catch (error) {
    toast.error(getErrorMessage(error, '刷新失败'))
  } finally {
    refreshing.value = false
  }
}

async function handleDownload() {
  try {
    await downloadIcs(props.api)
    toast.success('ICS 文件已下载')
  } catch (error) {
    console.error(error)
    toast.error('ICS 文件下载失败')
  }
}

async function handleCopyUrl() {
  const env = await loadSystemEnv(props.api)
  if (!env) {
    toast.warning('仅管理员可获取订阅链接，请在插件配置中复制')
    return
  }
  const ok = await copyText(buildSubscribeUrl(env.domain, env.token))
  if (ok) toast.success('iCal 订阅链接已复制，请妥善保管（包含 API 令牌）')
  else toast.error('复制失败，请检查浏览器权限')
}

function handleResize() {
  viewportWidth.value = window.innerWidth
}

watch(gridRange, () => void loadEvents())

onMounted(() => {
  window.addEventListener('resize', handleResize, { passive: true })
  void ensureImageSettings(props.api)
  void loadEvents()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  clearRefreshTimers()
})
</script>

<template>
  <div class="sc-calendar" :class="{ 'sc-calendar--embedded': embedded, 'sc-calendar--compact': compact }">
    <!-- 顶部工具栏 -->
    <div class="sc-toolbar">
      <div class="sc-toolbar__heading">
        <v-avatar color="primary" variant="tonal" rounded="lg" size="40">
          <v-icon icon="mdi-calendar-month-outline" />
        </v-avatar>
        <div class="sc-toolbar__title">
          <div class="text-h6 font-weight-bold">订阅日历</div>
          <div class="text-caption text-medium-emphasis">
            本月 {{ stats.shows }} 部 · {{ stats.total }} 次播出 · 今日 {{ stats.today }}
          </div>
        </div>
        <v-spacer />
        <template v-if="embedded">
          <v-btn v-if="showSwitch" icon="mdi-cog" variant="text" size="small" title="插件配置" @click="emit('switch')" />
          <v-btn icon="mdi-close" variant="text" size="small" title="关闭" @click="emit('close')" />
        </template>
      </div>

      <div class="sc-toolbar__controls">
        <div class="sc-toolbar__nav">
          <v-btn icon="mdi-chevron-left" variant="text" size="small" title="上个月" @click="shiftMonth(-1)" />
          <div class="sc-toolbar__month">{{ monthLabel }}</div>
          <v-btn icon="mdi-chevron-right" variant="text" size="small" title="下个月" @click="shiftMonth(1)" />
          <v-btn
            variant="tonal"
            size="small"
            color="primary"
            class="ms-1"
            @click="goToday"
          >
            今天
          </v-btn>
        </div>

        <div class="sc-toolbar__actions">
          <v-btn-toggle v-model="typeFilter" mandatory density="compact" variant="outlined" divided color="primary">
            <v-btn v-for="filter in TYPE_FILTERS" :key="filter.value" :value="filter.value" size="small">
              <v-icon :icon="filter.icon" size="16" class="me-1" />
              {{ filter.title }}
            </v-btn>
          </v-btn-toggle>
          <v-btn
            :icon="hideObtained ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
            variant="text"
            size="small"
            :color="hideObtained ? 'primary' : undefined"
            :title="hideObtained ? '显示已获取的剧集' : '隐藏已获取的剧集'"
            @click="hideObtained = !hideObtained"
          />
          <v-btn
            icon="mdi-refresh"
            variant="text"
            size="small"
            title="重新获取播出信息"
            :loading="refreshing"
            @click="refreshData"
          />
          <v-menu location="bottom end">
            <template #activator="{ props: menuProps }">
              <v-btn icon="mdi-dots-vertical" variant="text" size="small" v-bind="menuProps" />
            </template>
            <v-list density="compact" min-width="180">
              <v-list-item prepend-icon="mdi-download" title="下载 ICS 文件" @click="handleDownload" />
              <v-list-item prepend-icon="mdi-link-variant" title="复制 iCal 订阅链接" @click="handleCopyUrl" />
            </v-list>
          </v-menu>
        </div>
      </div>
    </div>

    <v-alert v-if="loadError" type="error" variant="tonal" density="compact" class="mb-3">
      {{ loadError }}
      <template #append>
        <v-btn size="small" variant="text" @click="loadEvents">重试</v-btn>
      </template>
    </v-alert>

    <!-- 月历视图 -->
    <v-card v-if="!compact" class="sc-board" :loading="loading">
      <div class="sc-board__weekdays">
        <div v-for="(label, index) in WEEK_LABELS" :key="label" class="sc-board__weekday" :class="{ 'sc-board__weekday--weekend': index >= 5 }">
          周{{ label }}
        </div>
      </div>
      <div class="sc-board__grid" :style="{ gridTemplateRows: `repeat(${gridRange.weeks}, minmax(7.5rem, 1fr))` }">
        <template v-for="week in weeks" :key="week.key">
          <div
            v-for="day in week.days"
            :key="day.key"
            class="sc-cell"
            :class="{
              'sc-cell--outside': !day.inMonth,
              'sc-cell--today': day.isToday,
              'sc-cell--past': day.isPast,
              'sc-cell--weekend': day.weekend,
              'sc-cell--has-items': day.items.length > 0,
            }"
            @click="day.items.length && openDay(day.key, day.items)"
          >
            <div class="sc-cell__head">
              <span class="sc-cell__day">{{ day.day }}</span>
              <span v-if="day.items.length > 3" class="sc-cell__count">{{ day.items.length }} 部</span>
            </div>
            <div class="sc-cell__events">
              <div
                v-for="item in day.items.slice(0, 3)"
                :key="item.uid"
                class="sc-cell-event"
                :class="{ 'sc-cell-event--obtained': item.downloaded }"
                :title="cellTitle(item)"
              >
                <v-img :src="getImageUrl(api, item.poster)" class="sc-cell-event__poster" cover aspect-ratio="0.667">
                  <template #error>
                    <div class="sc-cell-event__fallback" />
                  </template>
                </v-img>
                <div class="sc-cell-event__text">
                  <div class="sc-cell-event__name">{{ item.name || item.summary }}</div>
                  <div class="sc-cell-event__meta">
                    <span class="sc-cell-event__dot" :class="`sc-dot--${getDaypartColor(item).replace('#', '')}`" />
                    <span>{{ formatEpisode(item) || '上映' }}</span>
                    <span v-if="!item.all_day" class="text-medium-emphasis">{{ formatTimeRange(item).split(' - ')[0] }}</span>
                    <v-icon v-if="item.downloaded" icon="mdi-check-circle" size="12" color="success" />
                  </div>
                </div>
              </div>
              <div v-if="day.items.length > 3" class="sc-cell__more">还有 {{ day.items.length - 3 }} 个…</div>
            </div>
          </div>
        </template>
      </div>
    </v-card>

    <!-- 窄屏列表视图 -->
    <div v-else class="sc-agenda">
      <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-2" />
      <div v-if="!loading && !agendaDays.length" class="sc-agenda__empty text-medium-emphasis">
        <v-icon icon="mdi-calendar-blank-outline" size="40" />
        <span>本月没有播出的订阅</span>
      </div>
      <v-card v-for="day in agendaDays" :key="day.key" class="sc-agenda__day">
        <v-card-item class="py-2">
          <v-card-title class="text-subtitle-1" :class="{ 'text-primary': day.key === toDateKey(today) }">
            {{ formatDateLabel(day.key) }}
          </v-card-title>
          <template #append>
            <span class="text-caption text-medium-emphasis">{{ day.items.length }} 个播出</span>
          </template>
        </v-card-item>
        <v-card-text class="pt-0 pb-2 px-2">
          <EventRow v-for="item in day.items" :key="item.uid" :item="item" :api="api" @open-media="handleOpenMedia" />
        </v-card-text>
      </v-card>
    </div>

    <!-- 图例 -->
    <div class="sc-legend text-caption text-medium-emphasis">
      <span v-for="legend in LEGENDS" :key="legend.text" class="sc-legend__item">
        <span class="sc-cell-event__dot" :class="`sc-dot--${legend.color.replace('#', '')}`" />
        {{ legend.text }}
      </span>
      <span class="sc-legend__item">
        <v-icon icon="mdi-check-circle" size="12" color="success" />
        已获取
      </span>
    </div>

    <DayEventsDialog
      v-model="dialog.show"
      :date="dialog.date"
      :items="dialog.items"
      :api="api"
      @open-media="handleOpenMedia"
    />
  </div>
</template>

<style scoped>
.sc-calendar {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
}

.sc-calendar:not(.sc-calendar--embedded) {
  /* 预留 NEO 底部悬浮导航的空间 */
  padding-block-end: 5.5rem;
}

.sc-calendar--embedded {
  padding: 1rem 1rem 0.75rem;
}

.sc-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.sc-toolbar__heading {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.sc-toolbar__title {
  min-inline-size: 0;
}

.sc-toolbar__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.sc-toolbar__nav,
.sc-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

.sc-toolbar__month {
  min-inline-size: 6.5rem;
  font-size: 1.125rem;
  font-weight: 700;
  text-align: center;
}

/* 月历 */
.sc-board {
  overflow: hidden;
}

.sc-board__weekdays {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.sc-board__weekday {
  padding-block: 0.5rem;
  color: rgba(var(--v-theme-on-surface), 0.7);
  font-size: 0.8125rem;
  font-weight: 600;
  text-align: center;
}

.sc-board__weekday--weekend {
  color: rgb(var(--v-theme-primary));
}

.sc-board__grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.sc-cell {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-inline-size: 0;
  padding: 0.375rem;
  border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-inline-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  transition: background-color 0.2s ease;
}

.sc-cell:nth-child(7n) {
  border-inline-end: 0;
}

.sc-cell--weekend {
  background-color: rgba(var(--v-theme-on-surface), 0.015);
}

.sc-cell--has-items {
  cursor: pointer;
}

.sc-cell--has-items:hover {
  background-color: rgba(var(--v-theme-primary), 0.06);
}

.sc-cell--outside {
  opacity: 0.45;
}

.sc-cell--today {
  background-color: rgba(var(--v-theme-primary), 0.08);
  box-shadow: inset 0 0 0 1.5px rgba(var(--v-theme-primary), 0.55);
}

.sc-cell__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-block-size: 1.5rem;
}

.sc-cell__day {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  block-size: 1.5rem;
  font-size: 0.8125rem;
  font-weight: 600;
  min-inline-size: 1.5rem;
}

.sc-cell--today .sc-cell__day {
  background-color: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-on-primary));
}

.sc-cell--past:not(.sc-cell--today) .sc-cell__day {
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.sc-cell__count {
  color: rgba(var(--v-theme-on-surface), 0.55);
  font-size: 0.6875rem;
}

.sc-cell__events {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-block-size: 0;
}

.sc-cell-event {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-inline-size: 0;
  padding: 0.1875rem;
  border-radius: 6px;
  background-color: rgba(var(--v-theme-on-surface), 0.05);
}

.sc-cell-event--obtained {
  opacity: 0.7;
}

.sc-cell-event__poster {
  flex: 0 0 auto;
  border-radius: 3px;
  inline-size: 1.25rem;
}

.sc-cell-event__fallback {
  block-size: 100%;
  background-color: rgba(var(--v-theme-on-surface), 0.12);
}

.sc-cell-event__text {
  flex: 1 1 auto;
  min-inline-size: 0;
}

.sc-cell-event__name {
  overflow: hidden;
  color: rgb(var(--v-theme-on-surface));
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sc-cell-event__meta {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  overflow: hidden;
  font-size: 0.6875rem;
  line-height: 1.2;
  white-space: nowrap;
}

.sc-cell-event__dot {
  display: inline-block;
  flex: 0 0 auto;
  border-radius: 999px;
  block-size: 0.5rem;
  inline-size: 0.5rem;
}

.sc-dot--warning {
  background-color: rgb(var(--v-theme-warning));
}

.sc-dot--info {
  background-color: rgb(var(--v-theme-info));
}

.sc-dot--primary {
  background-color: rgb(var(--v-theme-primary));
}

.sc-dot--secondary {
  background-color: rgb(var(--v-theme-secondary));
}

.sc-dot--3949AB {
  background-color: #3949ab;
}

.sc-cell__more {
  padding-inline: 0.25rem;
  color: rgb(var(--v-theme-primary));
  font-size: 0.6875rem;
}

/* 列表 */
.sc-agenda {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.sc-agenda__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding-block: 3rem;
}

/* 图例 */
.sc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding-inline: 0.25rem;
}

.sc-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
</style>
