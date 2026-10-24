<script setup lang="ts">
import CalendarView from './CalendarView.vue'

// 插件详情弹窗
defineProps({
  api: {
    type: Object,
    required: true,
  },
  show_switch: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['action', 'switch', 'close'])
</script>

<template>
  <CalendarView :api="api" embedded :show-switch="show_switch" @close="emit('close')" @switch="emit('switch')" />
</template>
