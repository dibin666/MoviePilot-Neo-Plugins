<script setup lang="ts">
import CalendarView from './CalendarView.vue'

// 主应用侧栏全页：#/plugin-app/SubscribeCal/main
defineProps({
  api: {
    type: Object,
    required: true,
  },
  navKey: {
    type: String,
    default: 'main',
  },
  pluginId: {
    type: String,
    default: 'SubscribeCal',
  },
})

defineEmits(['action'])
</script>

<template>
  <CalendarView :api="api" />
</template>
