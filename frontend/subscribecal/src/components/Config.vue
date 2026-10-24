<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { PLUGIN_ID } from '../utils/calendar'
import { buildSubscribeUrl, copyText, downloadIcs, loadSystemEnv, useHostToast } from '../utils/actions'

const props = defineProps({
  api: {
    type: Object,
    required: true,
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['close', 'save', 'switch'])

const toast = useHostToast()

// 插件默认配置
const defaultConfig = {
  enabled: false,
  onlyonce: false,
  calc_time: false,
  sidebar_nav: true,
  calname: '追剧日历',
  interval_minutes: 15,
  cron: '',
  dashboard_size: 6,
}

type PluginConfig = typeof defaultConfig

const config = reactive<PluginConfig>({ ...defaultConfig })

const DASHBOARD_SIZES = [
  { title: '1/3 宽', value: 4 },
  { title: '1/2 宽', value: 6 },
  { title: '2/3 宽', value: 8 },
  { title: '3/4 宽', value: 9 },
  { title: '全宽', value: 12 },
]

const SWITCHES: { key: keyof PluginConfig; title: string; subtitle: string }[] = [
  { key: 'enabled', title: '启用插件', subtitle: '生成日历并开放 iCal 订阅' },
  { key: 'onlyonce', title: '立即刷新一次', subtitle: '保存后重新获取全部订阅的播出信息' },
  { key: 'calc_time', title: '推算播出时间', subtitle: '根据订阅下载记录推算具体播出时刻' },
  { key: 'sidebar_nav', title: '侧栏月历入口', subtitle: '在侧栏「订阅」分组显示订阅日历' },
]

const form = ref<{ validate: () => Promise<{ valid: boolean }> } | null>(null)
const saving = ref(false)
const downloading = ref(false)

// 订阅链接
const systemEnv = reactive({
  loaded: false,
  available: false,
  domain: '',
  token: '',
})
const showToken = ref(false)

const subscribeUrl = computed(() =>
  systemEnv.available ? buildSubscribeUrl(systemEnv.domain || window.location.origin, systemEnv.token) : '',
)

const displayUrl = computed(() => {
  if (!subscribeUrl.value) return ''
  if (showToken.value || !systemEnv.token) return subscribeUrl.value
  return subscribeUrl.value.replace(encodeURIComponent(systemEnv.token), '••••••')
})

const rules = {
  interval: (value: unknown) => {
    const number = Number(value)
    return (Number.isInteger(number) && number >= 0 && number <= 1440) || '请输入 0-1440 的整数'
  },
  cron: (value: unknown) => {
    const text = String(value ?? '').trim()
    return !text || text.split(/\s+/).length === 5 || '请输入 5 段 cron 表达式，如 0 */6 * * *'
  },
}

function normalizeConfig(): PluginConfig {
  return {
    ...config,
    calname: String(config.calname || '').trim() || defaultConfig.calname,
    cron: String(config.cron || '').trim(),
    interval_minutes: Number(config.interval_minutes) || 0,
    dashboard_size: Number(config.dashboard_size) || defaultConfig.dashboard_size,
  }
}

async function saveConfig() {
  const result = await form.value?.validate()
  if (result && !result.valid) {
    toast.warning('请检查配置项')
    return
  }
  saving.value = true
  try {
    emit('save', normalizeConfig())
  } finally {
    saving.value = false
  }
}

function resetForm() {
  Object.assign(config, defaultConfig)
}

async function handleDownload() {
  downloading.value = true
  try {
    await downloadIcs(props.api, config.calname)
    toast.success('ICS 文件已下载')
  } catch (error) {
    console.error(error)
    toast.error('ICS 文件下载失败，请确认插件已启用')
  } finally {
    downloading.value = false
  }
}

async function handleCopy() {
  if (!subscribeUrl.value) {
    toast.warning('无法获取订阅链接，请确认当前账号为管理员')
    return
  }
  const ok = await copyText(subscribeUrl.value)
  if (ok) toast.success('已复制到剪贴板')
  else toast.error('复制失败，请检查浏览器权限')
}

function openCalendar() {
  emit('close')
  window.location.hash = `/plugin-app/${PLUGIN_ID}/main`
}

onMounted(async () => {
  Object.keys(defaultConfig).forEach(key => {
    const value = props.initialConfig?.[key]
    if (value !== undefined && value !== null) (config as any)[key] = value
  })
  config.calc_time = Boolean(config.calc_time)

  const env = await loadSystemEnv(props.api)
  systemEnv.loaded = true
  if (env) {
    systemEnv.available = true
    systemEnv.domain = env.domain
    systemEnv.token = env.token
  }
})
</script>

<template>
  <v-card flat class="sc-config">
    <v-card-item>
      <v-card-title>订阅日历</v-card-title>
      <v-card-subtitle>根据订阅生成追剧日历，支持 iCal 订阅、仪表盘与侧栏月历</v-card-subtitle>
      <template #append>
        <v-btn icon="mdi-close" variant="text" size="small" @click="emit('close')" />
      </template>
    </v-card-item>

    <v-card-text>
      <v-form ref="form" @submit.prevent="saveConfig">
        <v-row>
          <v-col v-for="item in SWITCHES" :key="item.key" cols="12" md="6">
            <v-switch v-model="config[item.key]" :label="item.title" :hint="item.subtitle" persistent-hint />
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12" md="6">
            <v-text-field
              v-model="config.calname"
              label="日历名称"
              hint="设备日历中显示的名称"
              persistent-hint
              prepend-inner-icon="mdi-format-title"
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field
              v-model="config.cron"
              label="刷新周期"
              placeholder="0 */6 * * *"
              hint="5 段 cron 表达式，留空每 12 小时刷新"
              persistent-hint
              prepend-inner-icon="mdi-timer-cog-outline"
              :rules="[rules.cron]"
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field
              v-model.number="config.interval_minutes"
              label="时间取整间隔（分钟）"
              type="number"
              hint="推算播出时间时按此间隔向下取整"
              persistent-hint
              prepend-inner-icon="mdi-clock-time-four-outline"
              :disabled="!config.calc_time"
              :rules="[rules.interval]"
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-select
              v-model="config.dashboard_size"
              :items="DASHBOARD_SIZES"
              label="仪表盘默认宽度"
              hint="仪表盘编辑模式下可再自由调整"
              persistent-hint
              prepend-inner-icon="mdi-view-dashboard-outline"
            />
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12">
            <v-text-field
              v-model="systemEnv.domain"
              label="访问域名"
              placeholder="https://mp.example.com"
              hint="外部设备访问日历使用的地址，需公网可达"
              persistent-hint
              prepend-inner-icon="mdi-web"
              :disabled="!systemEnv.available"
            />
          </v-col>
          <v-col cols="12">
            <v-text-field
              :model-value="systemEnv.loaded && !systemEnv.available ? '仅管理员可查看订阅链接' : displayUrl"
              label="iCal 订阅链接"
              hint="链接包含 API 令牌，请妥善保管"
              persistent-hint
              prepend-inner-icon="mdi-link-variant"
              readonly
            >
              <template #append-inner>
                <v-btn
                  v-if="systemEnv.token"
                  :icon="showToken ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
                  variant="text"
                  size="small"
                  :title="showToken ? '隐藏令牌' : '显示令牌'"
                  @click="showToken = !showToken"
                />
                <v-btn icon="mdi-content-copy" variant="text" size="small" title="复制链接" @click="handleCopy" />
              </template>
            </v-text-field>
          </v-col>
          <v-col cols="12">
            <v-alert type="info" variant="tonal" density="compact">
              <div>将 iCal 链接添加到支持订阅的日历应用（iOS/macOS 日历、Outlook、Google Calendar 等）。</div>
              <div>未开启「推算播出时间」时，事件以全天事件显示；仅 TMDB 或 Bangumi 身份的订阅会生成日历，洗版订阅不生成。</div>
            </v-alert>
          </v-col>
        </v-row>
      </v-form>
    </v-card-text>

    <v-card-actions class="sc-config__actions">
      <v-btn variant="text" prepend-icon="mdi-download" :loading="downloading" @click="handleDownload">下载 ICS</v-btn>
      <v-btn variant="text" prepend-icon="mdi-calendar-month-outline" @click="openCalendar">打开月历</v-btn>
      <v-spacer />
      <v-btn variant="text" prepend-icon="mdi-restore" @click="resetForm">恢复默认</v-btn>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" @click="saveConfig">保存</v-btn>
    </v-card-actions>
  </v-card>
</template>

<style scoped>
.sc-config__actions {
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.75rem 1rem 1rem;
}
</style>
