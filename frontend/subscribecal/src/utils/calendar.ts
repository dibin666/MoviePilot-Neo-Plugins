import { ref } from 'vue'
import type { RawTimeLineItem, TimeLineGroup, TimeLineItem } from '../types'

export const PLUGIN_ID = 'SubscribeCal'

/** 将 Date 转换为本地时区下的 YYYY-MM-DD，避免 toISOString 的 UTC 跨天问题。 */
export function toDateKey(date: Date = new Date()): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 解析 YYYY-MM-DD 为本地零点 Date。 */
export function parseDateKey(value: string): Date {
  const [y, m, d] = value.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

/** 当天零点。 */
export function startOfToday(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

/** 日期加减天数。 */
export function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

/** 解析后端返回的 UTC 时间字符串（20250101T123456Z），非法时返回 null。 */
export function parseUTCDateTime(value?: string | null): Date | null {
  if (!value || !/^\d{8}T\d{6}Z$/.test(value)) return null
  return new Date(
    Date.UTC(
      Number(value.slice(0, 4)),
      Number(value.slice(4, 6)) - 1,
      Number(value.slice(6, 8)),
      Number(value.slice(9, 11)),
      Number(value.slice(11, 13)),
      Number(value.slice(13, 15)),
    ),
  )
}

/** 判断旧版数据是否为“时间未知”（本地 00:00 - 23:59）。 */
function isLegacyAllDay(start: Date, end?: Date | null): boolean {
  if (!end) return false
  return start.getHours() === 0 && start.getMinutes() === 0 && end.getHours() === 23 && end.getMinutes() === 59
}

/** 将接口返回的原始条目转换为前端条目。 */
export function normalizeItems(items: RawTimeLineItem[] | null | undefined): TimeLineItem[] {
  if (!Array.isArray(items)) return []
  const result: TimeLineItem[] = []
  for (const item of items) {
    const start = parseUTCDateTime(item.dtstart)
    if (!start) continue
    const end = parseUTCDateTime(item.dtend)
    const allDay = item.all_day ?? isLegacyAllDay(start, end)
    // 全天事件以服务端给出的播出日为准；定时事件按浏览器本地时间分组
    const date = allDay && item.date ? item.date : toDateKey(start)
    result.push({
      ...item,
      date,
      dtstart: start,
      dtend: end ?? undefined,
      all_day: allDay,
    })
  }
  return result
}

/** 事件排序：时间 -> 订阅 -> 集号。 */
export function compareItems(a: TimeLineItem, b: TimeLineItem): number {
  if (a.all_day !== b.all_day) return a.all_day ? 1 : -1
  const diff = a.dtstart.getTime() - b.dtstart.getTime()
  if (diff) return diff
  if (a.id !== b.id) return a.id - b.id
  return (a.episode ?? 0) - (b.episode ?? 0)
}

/** 按日期分组并排序。 */
export function groupByDate(items: TimeLineItem[]): TimeLineGroup[] {
  const map = new Map<string, TimeLineItem[]>()
  for (const item of items) {
    if (!map.has(item.date)) map.set(item.date, [])
    map.get(item.date)!.push(item)
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([date, groupItems]) => ({ date, items: groupItems.sort(compareItems) }))
}

/** 获取 API 基础路径（与主应用一致）。 */
export function getApiBase(api: any): string {
  const base = api?.defaults?.baseURL || '/api/v1/'
  return base.endsWith('/') ? base : `${base}/`
}

// 与主应用一致：仅在开启「全局图片缓存」时走后端缓存
const imageCacheEnabled = ref(false)
let imageSettingsPromise: Promise<void> | null = null

/** 读取主程序图片缓存设置（全局只请求一次）。 */
export function ensureImageSettings(api: any): Promise<void> {
  if (!imageSettingsPromise) {
    imageSettingsPromise = Promise.resolve(api?.get?.('system/global', { params: { token: 'moviepilot' } }))
      .then((result: any) => {
        imageCacheEnabled.value = Boolean(result?.data?.GLOBAL_IMAGE_CACHE)
      })
      .catch(() => {
        imageCacheEnabled.value = false
      })
  }
  return imageSettingsPromise
}

/** 图片地址：与主应用 getDisplayImageUrl 规则一致。 */
export function getImageUrl(api: any, url?: string | null): string {
  if (!url) return ''
  if (!/^https?:\/\//i.test(url)) return url
  const encoded = encodeURIComponent(url)
  const base = getApiBase(api)
  const useCache = imageCacheEnabled.value
  if (/(^|\.)lain\.bgm\.tv$/i.test(safeHostname(url)))
    return `${base}system/img/1?imgurl=${encoded}${useCache ? '&cache=true' : ''}`
  if (useCache) return `${base}system/cache/image?url=${encoded}`
  if (url.includes('doubanio.com')) return `${base}system/img/0?imgurl=${encoded}`
  return url
}

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}

/** 构造主应用媒体详情页使用的 mediaid。 */
export function getMediaId(item: Partial<TimeLineItem>): string | undefined {
  if (item.media_source && item.media_id) {
    const prefix = item.media_source === 'themoviedb' ? 'tmdb' : item.media_source
    return `${prefix}:${item.media_id}`
  }
  if (item.tmdbid) return `tmdb:${item.tmdbid}`
  if (item.doubanid) return `douban:${item.doubanid}`
  if (item.bangumiid) return `bangumi:${item.bangumiid}`
  if (item.anilistid) return `anilist:${item.anilistid}`
  return undefined
}

/** 跳转主应用媒体详情页（主应用使用 hash 路由）。 */
export function openMediaDetail(item: Partial<TimeLineItem>): boolean {
  const mediaid = getMediaId(item)
  if (!mediaid) return false
  const query = new URLSearchParams({ mediaid })
  if (item.name) query.set('title', item.name)
  if (item.year) query.set('year', String(item.year))
  if (item.type) query.set('type', item.type)
  window.location.hash = `/media?${query.toString()}`
  return true
}

/** 格式化 HH:mm。 */
export function formatTime(date?: Date | null): string {
  if (!date) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** 时间段文本。 */
export function formatTimeRange(item: TimeLineItem): string {
  if (item.all_day) return '时间待定'
  const start = formatTime(item.dtstart)
  const end = item.dtend && item.dtend.getTime() !== item.dtstart.getTime() ? formatTime(item.dtend) : ''
  return end ? `${start} - ${end}` : start
}

/** 季集文本。 */
export function formatEpisode(item: Partial<TimeLineItem>): string {
  if (item.type !== '电视剧' || item.episode == null) return ''
  const season = item.season != null ? `S${String(item.season).padStart(2, '0')}` : ''
  return `${season}E${String(item.episode).padStart(2, '0')}`
}

/** 播出时段颜色。 */
export function getDaypartColor(item: TimeLineItem): string {
  if (item.all_day) return 'secondary'
  const hour = item.dtstart.getHours()
  if (hour >= 6 && hour < 12) return 'warning'
  if (hour >= 12 && hour < 18) return 'info'
  if (hour >= 18 && hour < 23) return 'primary'
  return '#3949AB'
}

/** 播出时段文本。 */
export function getDaypartLabel(item: TimeLineItem): string {
  if (item.all_day) return '时间待定'
  const hour = item.dtstart.getHours()
  if (hour >= 6 && hour < 12) return '上午'
  if (hour >= 12 && hour < 18) return '下午'
  if (hour >= 18 && hour < 23) return '晚间'
  return '深夜'
}

/** 媒体类型图标。 */
export function getTypeIcon(type?: string): string {
  if (type === '电视剧') return 'mdi-television-play'
  if (type === '电影') return 'mdi-filmstrip'
  return 'mdi-help-box'
}

const STATE_META: Record<string, { text: string; color: string }> = {
  N: { text: '新建', color: 'info' },
  R: { text: '订阅中', color: 'success' },
  P: { text: '待定', color: 'warning' },
  S: { text: '暂停', color: 'grey' },
}

/** 订阅状态。 */
export function getStateMeta(state?: string) {
  return (state && STATE_META[state]) || null
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 日期友好文本：今天 / 明天 / 周X。 */
export function formatDateLabel(dateKey: string): string {
  const date = parseDateKey(dateKey)
  const diff = Math.round((date.getTime() - startOfToday().getTime()) / 86400000)
  const md = `${date.getMonth() + 1}月${date.getDate()}日`
  const relative = diff === 0 ? '今天' : diff === 1 ? '明天' : diff === -1 ? '昨天' : WEEKDAYS[date.getDay()]
  return `${md} · ${relative}`
}

/** 日期距今天数（负数为过去）。 */
export function daysFromToday(dateKey: string): number {
  return Math.round((parseDateKey(dateKey).getTime() - startOfToday().getTime()) / 86400000)
}

/** 统一提取接口错误信息。 */
export function getErrorMessage(error: unknown, fallback = '请求失败'): string {
  const anyError = error as any
  return anyError?.response?.data?.detail || anyError?.response?.data?.message || anyError?.message || fallback
}
