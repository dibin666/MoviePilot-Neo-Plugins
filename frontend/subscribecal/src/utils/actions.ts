import { inject } from 'vue'
import type { HostToast } from '../types'
import { PLUGIN_ID } from './calendar'

/** 获取主应用 Toast；宿主不支持时静默降级为控制台输出。 */
export function useHostToast(): HostToast {
  const toast = inject<HostToast | null>('moviepilot:toast', null)
  if (toast) return toast
  return {
    success: (message: string) => console.info(message),
    info: (message: string) => console.info(message),
    warning: (message: string) => console.warn(message),
    error: (message: string) => console.error(message),
  }
}

/** 下载 ICS 文件。 */
export async function downloadIcs(api: any, calname = '追剧日历') {
  const content = await api.get(`plugin/${PLUGIN_ID}/download/calendar.ics`, { responseType: 'text' })
  const blob = new Blob([typeof content === 'string' ? content : String(content ?? '')], {
    type: 'text/calendar;charset=utf-8',
  })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', `${calname || '追剧日历'}.ics`)
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}

/** 读取系统域名与 API 令牌（仅管理员可用）。 */
export async function loadSystemEnv(api: any): Promise<{ domain: string; token: string } | null> {
  try {
    const result = await api.get('system/env')
    if (!result?.success) return null
    return {
      domain: result.data?.APP_DOMAIN || window.location.origin,
      token: result.data?.API_TOKEN || '',
    }
  } catch (error) {
    console.warn('读取系统设置失败', error)
    return null
  }
}

/** 构造 iCal 订阅链接。 */
export function buildSubscribeUrl(domain: string, token: string): string {
  let base = (domain || window.location.origin).trim().replace(/\/+$/, '')
  if (!/^https?:\/\//i.test(base)) base = `http://${base}`
  const url = new URL(`${base}/api/v1/plugin/${PLUGIN_ID}/subscribe`)
  if (token) url.searchParams.append('apikey', token)
  return url.toString()
}

/** 复制文本，非安全上下文（HTTP）下回退到 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 回退到 execCommand
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  textarea.remove()
  return ok
}
