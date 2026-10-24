<template>
  <v-app :theme="dark ? 'dark' : 'light'">
    <v-app-bar color="primary">
      <v-app-bar-title>订阅日历 · 组件预览</v-app-bar-title>
      <v-btn :icon="dark ? 'mdi-weather-sunny' : 'mdi-weather-night'" @click="dark = !dark" />
    </v-app-bar>

    <v-main>
      <v-container fluid>
        <v-tabs v-model="activeTab" color="primary">
          <v-tab value="apppage">侧栏月历</v-tab>
          <v-tab value="dashboard">仪表盘</v-tab>
          <v-tab value="config">配置</v-tab>
          <v-tab value="page">详情</v-tab>
        </v-tabs>

        <v-window v-model="activeTab" class="mt-4">
          <v-window-item value="apppage">
            <AppPage :api="mockApi" />
          </v-window-item>
          <v-window-item value="dashboard">
            <div style="max-width: 760px">
              <Dashboard :api="mockApi" :config="dashboardConfig" :allow-refresh="true" />
            </div>
          </v-window-item>
          <v-window-item value="config">
            <Config :api="mockApi" :initial-config="mockConfig" @save="onSave" @close="log('close')" />
          </v-window-item>
          <v-window-item value="page">
            <v-card max-width="80rem">
              <Page :api="mockApi" @close="log('close')" @switch="log('switch')" />
            </v-card>
          </v-window-item>
        </v-window>
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref } from 'vue'
import AppPage from './components/AppPage.vue'
import Config from './components/Config.vue'
import Dashboard from './components/Dashboard.vue'
import Page from './components/Page.vue'

const activeTab = ref('apppage')
const dark = ref(false)

// 本地预览使用内联 SVG 海报，避免依赖后端图片代理
function mockPoster(hue) {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='200' height='300'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='hsl(${hue},70%,55%)'/><stop offset='1' stop-color='hsl(${hue + 40},70%,30%)'/></linearGradient></defs><rect width='200' height='300' fill='url(#g)'/></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function utc(date) {
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
}

function localKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

// 生成模拟数据：今天前后 40 天
function buildMockItems() {
  const shows = [
    { id: 1, name: '葬送的芙莉莲', year: '2023', type: '电视剧', tmdbid: 209867, hour: 23, minute: 0, step: 7, offset: -30, total: 28, state: 'R' },
    { id: 2, name: '间谍过家家', year: '2022', type: '电视剧', tmdbid: 120089, hour: 20, minute: 30, step: 7, offset: -20, total: 12, state: 'R' },
    { id: 3, name: '三体', year: '2023', type: '电视剧', tmdbid: 108545, hour: null, step: 1, offset: -5, total: 30, state: 'R' },
    { id: 4, name: '沙丘：第二部', year: '2024', type: '电影', tmdbid: 693134, hour: null, step: 0, offset: 3, total: 1, state: 'S' },
    { id: 5, name: '迷宫饭', year: '2024', type: '电视剧', tmdbid: 219246, hour: 9, minute: 0, step: 7, offset: -14, total: 24, state: 'P' },
  ]
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const items = []
  for (const show of shows) {
    const count = show.type === '电影' ? 1 : show.total
    for (let ep = 1; ep <= count; ep++) {
      const day = new Date(today)
      day.setDate(day.getDate() + show.offset + (ep - 1) * show.step)
      const start = new Date(day)
      const end = new Date(day)
      if (show.hour == null) {
        end.setHours(23, 59)
      } else {
        start.setHours(show.hour, show.minute)
        end.setHours(show.hour, show.minute + 24)
      }
      items.push({
        id: show.id,
        name: show.name,
        year: show.year,
        type: show.type,
        tmdbid: show.tmdbid,
        state: show.state,
        poster: mockPoster(show.id * 67),
        backdrop: mockPoster(show.id * 67 + 20),
        vote: 8.6,
        uid: `${show.id}-${ep}`,
        date: localKey(day),
        dtstart: utc(start),
        dtend: utc(end),
        all_day: show.hour == null,
        summary: show.type === '电影' ? `${show.name} (${show.year})` : `[${ep}/${show.total}]${show.name} (${show.year})`,
        season: show.type === '电影' ? null : 1,
        episode: show.type === '电影' ? null : ep,
        total_episodes: show.type === '电影' ? null : show.total,
        episode_name: show.type === '电影' ? null : `第 ${ep} 话`,
        downloaded: day < today,
      })
    }
  }
  return items
}

const mockItems = buildMockItems()

function inRange(item, start, end) {
  return item.date >= start && item.date <= end
}

const mockApi = {
  defaults: { baseURL: '/api/v1/' },
  get: async (url, options = {}) => {
    console.log('GET', url, options)
    await new Promise(resolve => setTimeout(resolve, 300))
    const params = options.params || {}
    if (url.endsWith('/grouped_events')) {
      const today = new Date()
      const start = new Date(today)
      start.setDate(start.getDate() - (params.before_days || 0))
      const end = new Date(today)
      end.setDate(end.getDate() + (params.after_days || 0))
      return mockItems.filter(item => inRange(item, localKey(start), localKey(end)))
    }
    if (url.endsWith('/events')) {
      return mockItems.filter(item => inRange(item, params.start, params.end))
    }
    if (url === 'system/env') {
      return { success: true, data: { APP_DOMAIN: 'https://mp.example.com', API_TOKEN: 'demo-token' } }
    }
    if (url.endsWith('calendar.ics')) {
      return 'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'
    }
    return []
  },
  post: async (url, data) => {
    console.log('POST', url, data)
    return { success: true, message: '已开始刷新日历数据' }
  },
}

const mockConfig = ref({
  enabled: true,
  calc_time: false,
  onlyonce: false,
  sidebar_nav: true,
  interval_minutes: 15,
  calname: '追剧日历',
  cron: '',
  dashboard_size: 6,
})

const dashboardConfig = {
  id: 'SubscribeCal',
  name: '订阅日历',
  attrs: { title: '订阅日历', border: true, refresh: 1800 },
}

function log(message) {
  console.log(message)
}

function onSave(config) {
  console.log('save', config)
}
</script>
