<script setup lang="ts">
import { computed } from 'vue'
import type { TimeLineItem } from '../../types'
import {
  formatEpisode,
  formatTimeRange,
  getDaypartColor,
  getImageUrl,
  getMediaId,
  getStateMeta,
  getTypeIcon,
} from '../../utils/calendar'

const props = defineProps({
  item: {
    type: Object as () => TimeLineItem,
    required: true,
  },
  api: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['open-media'])

const linkable = computed(() => !!getMediaId(props.item))
const episode = computed(() => formatEpisode(props.item))
const state = computed(() => getStateMeta(props.item.state))

function open() {
  if (linkable.value) emit('open-media', props.item)
}
</script>

<template>
  <div
    class="sc-event-row"
    :class="{ 'sc-event-row--link': linkable }"
    :role="linkable ? 'button' : undefined"
    :tabindex="linkable ? 0 : undefined"
    @click="open"
    @keydown.enter="open"
  >
    <div class="sc-event-row__poster">
      <v-img :src="getImageUrl(api, item.poster)" aspect-ratio="0.667" cover class="rounded">
        <template #placeholder>
          <div class="sc-event-row__placeholder">
            <v-icon :icon="getTypeIcon(item.type)" size="20" />
          </div>
        </template>
        <template #error>
          <div class="sc-event-row__placeholder">
            <v-icon :icon="getTypeIcon(item.type)" size="20" />
          </div>
        </template>
      </v-img>
    </div>
    <div class="sc-event-row__body">
      <div class="sc-event-row__title">
        {{ item.name || item.summary }}
        <span v-if="item.year" class="text-medium-emphasis font-weight-regular">({{ item.year }})</span>
      </div>
      <div class="sc-event-row__subtitle text-medium-emphasis">
        <template v-if="episode">
          <span class="font-weight-medium">{{ episode }}</span>
          <span v-if="item.total_episodes"> / 共 {{ item.total_episodes }} 集</span>
          <span v-if="item.episode_name"> · {{ item.episode_name }}</span>
        </template>
        <span v-else-if="item.type === '电影'">电影上映</span>
      </div>
      <div class="sc-event-row__chips">
        <v-chip size="x-small" variant="tonal" :color="getDaypartColor(item)" prepend-icon="mdi-clock-outline">
          {{ formatTimeRange(item) }}
        </v-chip>
        <v-chip v-if="state" size="x-small" variant="tonal" :color="state.color">
          {{ state.text }}
        </v-chip>
        <v-chip v-if="item.downloaded" size="x-small" variant="tonal" color="success" prepend-icon="mdi-check">
          已获取
        </v-chip>
        <span v-if="item.vote" class="sc-event-row__vote">
          <v-icon icon="mdi-star" size="14" color="warning" />
          {{ Number(item.vote).toFixed(1) }}
        </span>
      </div>
    </div>
    <v-icon v-if="linkable" icon="mdi-chevron-right" class="sc-event-row__arrow" />
  </div>
</template>

<style scoped>
.sc-event-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.5rem;
  border-radius: 10px;
  outline: none;
  transition: background-color 0.2s ease;
}

.sc-event-row--link {
  cursor: pointer;
}

.sc-event-row--link:hover,
.sc-event-row--link:focus-visible {
  background-color: rgba(var(--v-theme-on-surface), 0.06);
}

.sc-event-row__poster {
  flex: 0 0 auto;
  inline-size: 52px;
}

.sc-event-row__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  block-size: 100%;
  inline-size: 100%;
  background: rgba(var(--v-theme-on-surface), 0.08);
  color: rgba(var(--v-theme-on-surface), 0.5);
}

.sc-event-row__body {
  flex: 1 1 auto;
  min-inline-size: 0;
}

.sc-event-row__title {
  overflow: hidden;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sc-event-row__subtitle {
  overflow: hidden;
  font-size: 0.8125rem;
  line-height: 1.4;
  margin-block: 0.125rem 0.375rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sc-event-row__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
}

.sc-event-row__vote {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
}

.sc-event-row__arrow {
  flex: 0 0 auto;
  color: rgba(var(--v-theme-on-surface), 0.45);
}
</style>
