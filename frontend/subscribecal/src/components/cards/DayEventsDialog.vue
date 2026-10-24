<script setup lang="ts">
import { computed } from 'vue'
import EventRow from './EventRow.vue'
import type { TimeLineItem } from '../../types'
import { compareItems, formatDateLabel } from '../../utils/calendar'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  date: {
    type: String,
    default: '',
  },
  items: {
    type: Array as () => TimeLineItem[],
    default: () => [],
  },
  api: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['update:modelValue', 'open-media'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

const sortedItems = computed(() => [...props.items].sort(compareItems))

const title = computed(() => (props.date ? formatDateLabel(props.date) : ''))
</script>

<template>
  <v-dialog v-model="visible" max-width="40rem" scrollable>
    <v-card class="sc-day-dialog">
      <v-card-item>
        <template #prepend>
          <v-icon icon="mdi-calendar-today" color="primary" />
        </template>
        <v-card-title>{{ title }}</v-card-title>
        <v-card-subtitle>共 {{ sortedItems.length }} 个播出</v-card-subtitle>
        <template #append>
          <v-btn icon="mdi-close" variant="text" size="small" @click="visible = false" />
        </template>
      </v-card-item>
      <v-divider />
      <v-card-text class="sc-day-dialog__body">
        <div v-if="!sortedItems.length" class="sc-day-dialog__empty text-medium-emphasis">
          <v-icon icon="mdi-calendar-blank-outline" size="36" />
          <span>当天没有播出</span>
        </div>
        <EventRow
          v-for="item in sortedItems"
          :key="item.uid"
          :item="item"
          :api="api"
          @open-media="emit('open-media', $event)"
        />
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.sc-day-dialog__body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  max-block-size: 70vh;
  padding-block: 0.5rem;
}

.sc-day-dialog__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding-block: 2rem;
}
</style>
