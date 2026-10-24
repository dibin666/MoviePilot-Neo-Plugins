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

const SWITCHES: { key: keyof PluginConfig; title: string; subtitle: string; icon: string }[] = [
  { key: 'enabled', title: '启用插件', subtitle: '生成日历并开放 iCal 订阅', icon: 'mdi-power' },
  { key: 'onlyonce', title: '立即刷新一次', subtitle: '保存后重新获取全部播出信息', icon: 'mdi-update' },
  { key: 'calc_time', title: '推算播出时间', subtitle: '根据订阅下载记录推算具体时刻', icon: 'mdi-history' },
  { key: 'sidebar_nav', title: '侧栏月历入口', subtitle: '在「订阅」分组显示月历页面', icon: 'mdi-dock-left' },
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
      <template #prepend>
        <v-avatar color="primary" variant="tonal" rounded="lg" size="38">
          <v-icon icon="mdi-calendar-month-outline" />
        </v-avatar>
      </template>
      <v-card-title>订阅日历</v-card-title>
      <v-card-subtitle>根据订阅生成追剧日历，支持 iCal 订阅、仪表盘与侧栏月历</v-card-subtitle>
      <template #append>
        <v-btn icon="mdi-close" variant="text" size="small" @click="emit('close')" />
      </template>
    </v-card-item>

    <v-divider />

    <v-card-text>
      <v-form ref="form" @submit.prevent="saveConfig">
        <!-- 开关 -->
        <div class="sc-section-title">基础设置</div>
        <v-row dense>
          <v-col v-for="item in SWITCHES" :key="item.key" cols="12" sm="6" lg="3">
            <div class="sc-switch-tile" :class="{ 'sc-switch-tile--active': !!config[item.key] }">
              <v-icon :icon="item.icon" size="20" :color="config[item.key] ? 'primary' : undefined" class="sc-switch-tile__icon" />
              <div class="sc-switch-tile__text">
                <div class="sc-switch-tile__title">{{ item.title }}</div>
                <div class="sc-switch-tile__subtitle">{{ item.subtitle }}</div>
              </div>
              <v-switch v-model="config[item.key]" color="primary" density="compact" hide-details inset />
            </div>
          </v-col>
        </v-row>

        <!-- 参数 -->
        <div class="sc-section-title mt-4">参数</div>
        <v-row dense>
          <v-col cols="12" sm="6" md="3">
            <v-text-field
              v-model="config.calname"
              label="日历名称"
              prepend-inner-icon="mdi-format-title"
              density="comfortable"
              hint="设备日历中显示的名称"
              persistent-hint
            />
          </v-col>
          <v-col cols="12" sm="6" md="3">
            <v-text-field
              v-model="config.cron"
              label="刷新周期"
              prepend-inner-icon="mdi-timer-cog-outline"
              placeholder="0 */6 * * *"
              density="comfortable"
              hint="cron 表达式，留空则每 12 小时刷新"
              persistent-hint
              :rules="[rules.cron]"
            />
          </v-col>
          <v-col cols="12" sm="6" md="3">
            <v-text-field
              v-model.number="config.interval_minutes"
              label="时间取整间隔"
              type="number"
              suffix="分钟"
              prepend-inner-icon="mdi-clock-time-four-outline"
              density="comfortable"
              hint="推算播出时间时按此间隔向下取整"
              persistent-hint
              :disabled="!config.calc_time"
              :rules="[rules.interval]"
            />
          </v-col>
          <v-col cols="12" sm="6" md="3">
            <v-select
              v-model="config.dashboard_size"
              :items="DASHBOARD_SIZES"
              label="仪表盘默认宽度"
              prepend-inner-icon="mdi-view-dashboard-outline"
              density="comfortable"
              hint="仪表盘编辑模式下可再自由调整"
              persistent-hint
            />
          </v-col>
        </v-row>

        <!-- 订阅 -->
        <div class="sc-section-title mt-4">日历订阅</div>
        <v-row dense align="center">
          <v-col cols="12" md="3">
            <v-text-field
              v-model="systemEnv.domain"
              label="访问域名"
              prepend-inner-icon="mdi-web"
              placeholder="https://mp.example.com"
              density="comfortable"
              :disabled="!systemEnv.available"
              hide-details
            />
          </v-col>
          <v-col cols="12" md="9">
            <v-text-field
              :model-value="systemEnv.loaded && !systemEnv.available ? '仅管理员可查看订阅链接' : displayUrl"
              label="iCal 订阅链接"
              prepend-inner-icon="mdi-link-variant"
              density="comfortable"
              readonly
              hide-details
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
                <v-btn icon="mdi-content-copy" variant="text" size="small" title="复制链接" color="primary" @click="handleCopy" />
              </template>
            </v-text-field>
          </v-col>
        </v-row>

        <v-alert type="info" variant="tonal" density="compact" class="mt-3">
          <ul class="sc-tips">
            <li>将 iCal 链接添加到支持订阅的日历应用（iOS/macOS 日历、Outlook、Google Calendar 等）。</li>
            <li>链接包含 API 令牌，请妥善保管，防止泄露。</li>
            <li>外部设备访问需要公网可达的域名或 IP，请按实际访问地址修改「访问域名」。</li>
            <li>未开启「推算播出时间」时，事件以全天事件显示；只有 TMDB 或 Bangumi 身份的订阅会生成日历，洗版订阅不生成。</li>
          </ul>
        </v-alert>
      </v-form>
    </v-card-text>

    <v-divider />

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
.sc-section-title {
  margin-block-end: 0.5rem;
  color: rgba(var(--v-theme-on-surface), 0.6);
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.sc-switch-tile {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  block-size: 100%;
  padding: 0.625rem 0.75rem;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 10px;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.sc-switch-tile--active {
  border-color: rgba(var(--v-theme-primary), 0.45);
  background-color: rgba(var(--v-theme-primary), 0.06);
}

.sc-switch-tile__icon {
  flex: 0 0 auto;
}

.sc-switch-tile__text {
  flex: 1 1 auto;
  min-inline-size: 0;
}

.sc-switch-tile__title {
  font-size: 0.875rem;
  font-weight: 600;
}

.sc-switch-tile__subtitle {
  color: rgba(var(--v-theme-on-surface), 0.6);
  font-size: 0.75rem;
  line-height: 1.35;
}

.sc-tips {
  margin: 0;
  padding-inline-start: 1.125rem;
}

.sc-tips li + li {
  margin-block-start: 0.25rem;
}

.sc-config__actions {
  flex-wrap: wrap;
  padding: 0.75rem 1rem;
}
</style>
