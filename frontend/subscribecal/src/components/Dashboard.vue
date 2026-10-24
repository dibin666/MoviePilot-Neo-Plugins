<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import CalendarEvent from './cards/CalendarEvent.vue'
import DayEventsDialog from './cards/DayEventsDialog.vue'
import type { TimeLineGroup, TimeLineItem } from '../types'
import { daysFromToday, groupByDate, normalizeItems, openMediaDetail, PLUGIN_ID, toDateKey } from '../utils/calendar'

const props = defineProps({
  config: {
    type: Object,
    default: () => ({}),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
  api: {
    type: Object,
    required: true,
  },
})

const TIMELINE_TARGET_SELECTORS = [
  '.v-timeline-divider__dot',
  '.v-timeline-item__dot',
  '.v-timeline-divider',
  '.v-timeline-item__divider',
  '.v-timeline-divider__inner-dot',
]

// 已加载的全部条目（按 uid 去重）
const itemMap = reactive(new Map<string, TimeLineItem>())

const loadingState = reactive({
  initial: true,
  future: false,
  error: false,
})

const viewState = reactive({
  userScrolled: false,
  hasCenteredInitialItem: false,
})

const timelineContainerRef = ref<HTMLElement | null>(null)

// 区分“用户触发的滚动”与“程序居中触发的滚动”
const scrollState = reactive({
  pointerIntent: false,
  suppressTracking: false,
})

// 已经向接口请求过的时间范围
const loadedRange = reactive({
  before: 0,
  after: 0,
})

// 当天详情弹窗
const dialog = reactive({
  show: false,
  date: '',
  items: [] as TimeLineItem[],
})

let suppressScrollTrackingTimer: ReturnType<typeof setTimeout> | null = null
let restoreScrollBehaviorTimer: ReturnType<typeof setTimeout> | null = null
// 用户接管滚动后锁定基准索引，避免增量加载导致视觉中心漂移
let fixedBaseIndex = -1

const title = computed(() => props.config?.attrs?.title || '订阅日历')

const timelineGroups = computed<TimeLineGroup[]>(() => groupByDate(Array.from(itemMap.values())))

// 请求接口并合并结果
async function fetchTimelineGroups(beforeDays: number, afterDays: number) {
  try {
    const response = await props.api.get(`plugin/${PLUGIN_ID}/grouped_events`, {
      params: { before_days: beforeDays, after_days: afterDays },
    })
    normalizeItems(response).forEach(item => itemMap.set(item.uid, item))
    loadedRange.before = Math.max(loadedRange.before, beforeDays)
    loadedRange.after = Math.max(loadedRange.after, afterDays)
    loadingState.error = false
  } catch (error) {
    console.error(error)
    loadingState.error = true
  }
}

// 主应用按 refresh 周期刷新配置时，静默重新拉取已加载范围
async function silentRefresh() {
  if (!props.allowRefresh || loadingState.initial) return
  try {
    const response = await props.api.get(`plugin/${PLUGIN_ID}/grouped_events`, {
      params: { before_days: loadedRange.before, after_days: loadedRange.after },
    })
    itemMap.clear()
    normalizeItems(response).forEach(item => itemMap.set(item.uid, item))
  } catch (error) {
    console.error(error)
  }
}

async function loadMoreFutureGroups() {
  if (loadingState.future || loadedRange.after >= 120) return
  loadingState.future = true
  try {
    await fetchTimelineGroups(loadedRange.before, loadedRange.after + 7)
  } finally {
    loadingState.future = false
  }
}

// 基准日期索引：默认今天，今天无事件时回退到最近的未来日期
function getBaseIndex(groups: TimeLineGroup[]): number {
  if (!groups.length) return -1
  if (viewState.userScrolled && fixedBaseIndex >= 0) return fixedBaseIndex

  const todayKey = toDateKey()
  const todayIndex = groups.findIndex(group => group.date === todayKey)
  if (todayIndex !== -1) return todayIndex

  const futureIndex = groups.findIndex(group => group.date >= todayKey)
  return futureIndex !== -1 ? futureIndex : groups.length - 1
}

// 首次居中目标：离今天最近的日期
function getTargetGroupDate(groups: TimeLineGroup[]): string | null {
  if (!groups.length) return null
  return groups.reduce((nearest, group) =>
    Math.abs(daysFromToday(group.date)) < Math.abs(daysFromToday(nearest.date)) ? group : nearest,
  ).date
}

function getTimelineTargetElement(targetDate: string): HTMLElement | null {
  const container = timelineContainerRef.value
  if (!container) return null
  const timelineItem = container.querySelector<HTMLElement>(`.sc-timeline-item[data-group-date="${targetDate}"]`)
  if (!timelineItem) return null
  for (const selector of TIMELINE_TARGET_SELECTORS) {
    const target = timelineItem.querySelector<HTMLElement>(selector)
    if (target) return target
  }
  return timelineItem.querySelector<HTMLElement>('.sc-timeline-anchor')
}

function holdScrollTracking(duration = 180) {
  scrollState.suppressTracking = true
  if (suppressScrollTrackingTimer) clearTimeout(suppressScrollTrackingTimer)
  suppressScrollTrackingTimer = setTimeout(() => {
    scrollState.suppressTracking = false
    suppressScrollTrackingTimer = null
  }, duration)
}

function scrollTargetToCenter(target: HTMLElement, container: HTMLElement) {
  const maxScrollLeft = Math.max(0, container.scrollWidth - container.clientWidth)
  if (maxScrollLeft <= 0) return

  const targetRect = target.getBoundingClientRect()
  const containerRect = container.getBoundingClientRect()
  const targetCenter = targetRect.left - containerRect.left + container.scrollLeft + targetRect.width / 2
  const nextScrollLeft = Math.min(Math.max(0, targetCenter - container.clientWidth / 2), maxScrollLeft)

  if (restoreScrollBehaviorTimer) clearTimeout(restoreScrollBehaviorTimer)
  holdScrollTracking()
  container.style.scrollBehavior = 'auto'
  container.scrollTo({ left: nextScrollLeft, behavior: 'auto' })
  restoreScrollBehaviorTimer = setTimeout(() => {
    container.style.scrollBehavior = ''
    restoreScrollBehaviorTimer = null
  }, 0)
}

// 先大致居中，布局稳定后再二次校正
async function centerTimelineItem() {
  if (viewState.hasCenteredInitialItem) return
  await nextTick()
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const targetDate = getTargetGroupDate(displayedGroups.value)
      const container = timelineContainerRef.value
      if (!container || !targetDate) return
      const first = getTimelineTargetElement(targetDate)
      if (!first) return
      scrollTargetToCenter(first, container)
      requestAnimationFrame(() => {
        const corrected = getTimelineTargetElement(targetDate)
        const correctedContainer = timelineContainerRef.value
        if (!corrected || !correctedContainer) return
        scrollTargetToCenter(corrected, correctedContainer)
        viewState.hasCenteredInitialItem = true
      })
    })
  })
}

// 初始只展示“已加载的过去 + 基准点后 4 组”，用户滚动后展示全部
const displayedGroups = computed(() => {
  const groups = timelineGroups.value
  const baseIndex = getBaseIndex(groups)
  if (baseIndex === -1) return []
  if (viewState.userScrolled) return groups
  return groups.slice(0, Math.min(groups.length - 1, baseIndex + 4) + 1)
})

function getStatusColor(group: TimeLineGroup): string {
  const diff = daysFromToday(group.date)
  if (diff < 0) return 'rgba(var(--v-theme-on-surface), 0.28)'
  if (diff === 0) return 'success'
  if (diff <= 3) return 'warning'
  return 'primary'
}

function getTimelineItemSize(group: TimeLineGroup): string {
  if (group.items.length === 1) return 'x-small'
  if (group.items.length <= 4) return 'small'
  return 'default'
}

function getDateLabel(date: string): string {
  const diff = daysFromToday(date)
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff === -1) return '昨天'
  return date.slice(5)
}

function markUserScrolled() {
  if (viewState.userScrolled) return
  fixedBaseIndex = getBaseIndex(timelineGroups.value)
  viewState.userScrolled = true
}

function handleTimelinePointerDown() {
  scrollState.pointerIntent = true
}

function clearTimelinePointerIntent() {
  scrollState.pointerIntent = false
}

function handleTimelineScroll() {
  const container = timelineContainerRef.value
  if (!container || scrollState.suppressTracking) return
  if (scrollState.pointerIntent) {
    markUserScrolled()
    scrollState.pointerIntent = false
  }
  const distanceToRight = container.scrollWidth - container.clientWidth - container.scrollLeft
  if (distanceToRight <= 200) void loadMoreFutureGroups()
}

// 鼠标滚轮纵向输入映射为横向滚动
function handleTimelineWheel(event: WheelEvent) {
  const container = timelineContainerRef.value
  if (!container || container.scrollWidth <= container.clientWidth) return
  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
  if (!delta) return
  markUserScrolled()
  scrollState.pointerIntent = false
  event.preventDefault()
  container.scrollLeft += delta
  handleTimelineScroll()
}

function openDay(group: TimeLineGroup) {
  dialog.date = group.date
  dialog.items = group.items
  dialog.show = true
}

function handleOpenMedia(item: TimeLineItem) {
  dialog.show = false
  openMediaDetail(item)
}

function openMonthView() {
  window.location.hash = `/plugin-app/${PLUGIN_ID}/main`
}

watch(
  displayedGroups,
  async groups => {
    if (!loadingState.initial && groups.length) await centerTimelineItem()
  },
  { flush: 'post' },
)

watch(
  () => props.config,
  () => void silentRefresh(),
)

// 初始化：预取今天前 10 天、后 7 天的数据
onMounted(async () => {
  await fetchTimelineGroups(10, 7)
  loadingState.initial = false
  await centerTimelineItem()
})

onActivated(async () => {
  if (!viewState.hasCenteredInitialItem) await centerTimelineItem()
})

onDeactivated(() => {
  viewState.hasCenteredInitialItem = false
})
</script>

<template>
  <v-card class="sc-dashboard dashboard-grid-fill">
    <v-card-item class="sc-dashboard__header">
      <v-card-title>{{ title }}</v-card-title>
      <template #append>
        <v-btn
          class="dashboard-grid-no-drag"
          icon="mdi-calendar-month-outline"
          size="small"
          variant="text"
          title="打开月历"
          @click="openMonthView"
        />
      </template>
    </v-card-item>

    <v-card-text class="sc-dashboard__body">
      <div v-if="loadingState.initial" class="sc-dashboard__state">
        <v-progress-circular indeterminate color="primary" />
      </div>

      <div v-else-if="!displayedGroups.length" class="sc-dashboard__state text-medium-emphasis">
        <v-icon :icon="loadingState.error ? 'mdi-alert-circle-outline' : 'mdi-calendar-blank-outline'" size="32" />
        <span>{{ loadingState.error ? '日历数据加载失败' : '近期没有播出的订阅' }}</span>
      </div>

      <div
        v-else
        ref="timelineContainerRef"
        class="sc-dashboard__scroller dashboard-grid-no-drag"
        @pointerdown="handleTimelinePointerDown"
        @pointerup="clearTimelinePointerIntent"
        @pointercancel="clearTimelinePointerIntent"
        @scroll="handleTimelineScroll"
        @wheel="handleTimelineWheel"
      >
        <div class="sc-dashboard__track">
          <v-timeline direction="horizontal" align="center" line-color="primary" class="sc-timeline">
            <v-timeline-item
              v-for="(group, index) in displayedGroups"
              :key="group.date"
              class="sc-timeline-item"
              :data-group-date="group.date"
              :dot-color="getStatusColor(group)"
              :size="getTimelineItemSize(group)"
            >
              <template #opposite>
                <span class="sc-timeline-date" :class="{ 'sc-timeline-date--today': daysFromToday(group.date) === 0 }">
                  {{ getDateLabel(group.date) }}
                </span>
              </template>

              <div class="sc-timeline-anchor" aria-hidden="true" />

              <CalendarEvent :events="group" :api="api" :position="index % 2 === 0 ? 'top' : 'bottom'" @select="openDay" />
            </v-timeline-item>
          </v-timeline>
        </div>
      </div>
    </v-card-text>

    <DayEventsDialog
      v-model="dialog.show"
      :date="dialog.date"
      :items="dialog.items"
      :api="api"
      @open-media="handleOpenMedia"
    />
  </v-card>
</template>

<style scoped>
.sc-dashboard {
  display: flex;
  flex-direction: column;
  block-size: 100%;
  min-block-size: 0;
}

.sc-dashboard__header {
  padding-block-end: 0;
}

.sc-dashboard__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  justify-content: center;
  min-block-size: 0;
  overflow: hidden;
}

.sc-dashboard__state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  min-block-size: 240px;
}

.sc-dashboard__scroller {
  flex: 1 1 auto;
  overflow-x: auto;
  overflow-y: hidden;
  overscroll-behavior-x: contain;
  scroll-behavior: smooth;
  scrollbar-width: thin;
}

.sc-dashboard__track {
  display: inline-flex;
  min-inline-size: max-content;
}

.sc-timeline-item {
  position: relative;
}

.sc-timeline-anchor {
  position: absolute;
  inset-block-start: 0;
  inset-inline-start: 50%;
  block-size: 0;
  inline-size: 0;
  pointer-events: none;
}

.sc-timeline-date {
  color: rgba(var(--v-theme-on-surface), 0.7);
  font-size: 0.8125rem;
  white-space: nowrap;
}

.sc-timeline-date--today {
  color: rgb(var(--v-theme-success));
  font-weight: 700;
}
</style>
