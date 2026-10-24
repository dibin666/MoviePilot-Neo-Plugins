<script setup lang="ts">
import { computed } from 'vue'
import type { TimeLineGroup, TimeLineItem } from '../../types'
import { compareItems, formatEpisode, getImageUrl } from '../../utils/calendar'

const props = defineProps({
  events: {
    type: Object as () => TimeLineGroup,
    default: () => ({ date: '', items: [] }),
  },
  position: {
    type: String,
    default: 'top',
  },
  api: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['select'])

const sortedEvents = computed<TimeLineItem[]>(() => [...(props.events?.items ?? [])].sort(compareItems))

// 按订阅去重，最多叠放 4 张图片
const uniqueEvents = computed<TimeLineItem[]>(() => {
  const seen = new Set<number>()
  const result: TimeLineItem[] = []
  for (const event of sortedEvents.value) {
    if (seen.has(event.id)) continue
    seen.add(event.id)
    result.push(event)
    if (result.length >= 4) break
  }
  return result
})

const caption = computed(() => {
  const first = sortedEvents.value[0]
  if (!first) return ''
  const episode = formatEpisode(first)
  const title = first.name || first.summary
  return episode ? `${title} ${episode}` : title
})

const moreCount = computed(() => Math.max(0, sortedEvents.value.length - 1))

function imageOf(event: TimeLineItem, index: number) {
  const url = index === 0 ? event.poster || event.backdrop : event.backdrop || event.poster
  return getImageUrl(props.api, url)
}
</script>

<template>
  <div class="sc-stack" role="button" tabindex="0" @click="emit('select', events)" @keydown.enter="emit('select', events)">
    <div class="sc-stack__cards">
      <div
        v-for="(event, index) in uniqueEvents"
        :key="event.id"
        class="sc-stack__image"
        :class="`sc-stack__image--${position}`"
      >
        <img :src="imageOf(event, index)" :alt="event.name || event.summary" loading="lazy" />
      </div>

      <div class="sc-stack__title" :class="`sc-stack__title--${position}`">
        {{ caption }}
        <span v-if="moreCount" class="sc-stack__more">+{{ moreCount }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sc-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  outline: none;
}

.sc-stack__cards {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1 / 1;
  inline-size: 150px;
}

.sc-stack__image {
  position: absolute;
  overflow: hidden;
  padding: 2px;
  border-radius: 6px;
  background: rgb(var(--v-theme-surface));
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.sc-stack__image img {
  display: block;
  block-size: 100%;
  border-radius: 4px;
  inline-size: 100%;
  object-fit: cover;
}

.sc-stack__image:nth-child(1) {
  z-index: 4;
  block-size: 68%;
  inline-size: 45%;
}

.sc-stack__image:nth-child(2) {
  z-index: 2;
  block-size: 35%;
  inline-size: 55%;
}

.sc-stack__image:nth-child(3) {
  z-index: 3;
  block-size: 35%;
  inline-size: 50%;
}

.sc-stack__image:nth-child(4) {
  z-index: 1;
  block-size: 40%;
  inline-size: 60%;
}

.sc-stack__image--top:nth-child(1) {
  inset-block-end: 0;
  inset-inline-end: 0;
}

.sc-stack__image--top:nth-child(2) {
  inset-block-start: 2%;
  inset-inline-end: 3%;
}

.sc-stack__image--top:nth-child(3) {
  inset-block-start: 25%;
  inset-inline-start: 10%;
}

.sc-stack__image--top:nth-child(4) {
  inset-block-start: 0;
  inset-inline-start: 0;
}

.sc-stack__image--bottom:nth-child(1) {
  inset-block-start: 0;
  inset-inline-start: 0;
}

.sc-stack__image--bottom:nth-child(2) {
  inset-block-start: 62%;
  inset-inline-start: 3%;
}

.sc-stack__image--bottom:nth-child(3) {
  inset-block-start: 35%;
  inset-inline-start: 40%;
}

.sc-stack__image--bottom:nth-child(4) {
  inset-block-start: 60%;
  inset-inline-start: 40%;
}

.sc-stack:hover .sc-stack__image:hover,
.sc-stack:focus-visible .sc-stack__image:first-child {
  z-index: 10;
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.25);
  transform: translateY(-10px);
}

.sc-stack__title {
  position: absolute;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  color: rgb(var(--v-theme-primary));
  font-size: 0.75rem;
  font-weight: 600;
  inline-size: 45%;
  line-height: 1.3;
  text-align: center;
  white-space: normal;
}

.sc-stack__title--top {
  border-block-start: 1px solid rgba(var(--v-theme-primary), 0.6);
  inset-block-end: 0;
  inset-inline-start: 3%;
  padding-block-start: 2%;
}

.sc-stack__title--bottom {
  border-block-end: 1px solid rgba(var(--v-theme-primary), 0.6);
  inset-block-start: 0;
  inset-inline-end: 3%;
  padding-block-end: 2%;
}

.sc-stack__more {
  margin-inline-start: 0.125rem;
  color: rgba(var(--v-theme-on-surface), 0.6);
  font-weight: 500;
}
</style>
