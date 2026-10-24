// 后端返回的日历条目（订阅信息 + 事件信息）
export interface RawTimeLineItem {
  // 订阅表ID
  id: number
  // 本地播出日期 YYYY-MM-DD（服务端时区）
  date?: string
  // 起始时间（UTC，20250101T123000Z）
  dtstart: string
  // 结束时间（UTC）
  dtend?: string
  // 是否全天（播出时间未知）
  all_day?: boolean
  // 标题
  summary: string
  // 订阅名称
  name?: string
  // 集标题
  episode_name?: string
  // 描述
  description?: string
  // 唯一标识
  uid: string
  // 年份
  year?: string
  // 类型：电影 / 电视剧
  type?: string
  // 季号
  season?: number
  // 集号
  episode?: number
  // 总集数
  total_episodes?: number
  // 海报
  poster?: string
  // 背景图
  backdrop?: string
  // 评分
  vote?: number | null
  // 状态：N-新建 R-订阅中 P-待定 S-暂停
  state?: string
  // 是否已下载/已入库
  downloaded?: boolean
  // 媒体身份
  tmdbid?: number
  doubanid?: string
  bangumiid?: number
  anilistid?: number
  media_source?: string
  media_id?: string
}

// 前端使用的日历条目，时间已转为 Date
export interface TimeLineItem extends Omit<RawTimeLineItem, 'dtstart' | 'dtend'> {
  // 分组日期 YYYY-MM-DD
  date: string
  dtstart: Date
  dtend?: Date
  all_day: boolean
}

// 日历事件组
export interface TimeLineGroup {
  // 日期
  date: string
  // 事件列表
  items: TimeLineItem[]
}

// 主应用 Toast
export interface HostToast {
  error(message: string): unknown
  info(message: string): unknown
  success(message: string): unknown
  warning(message: string): unknown
}
