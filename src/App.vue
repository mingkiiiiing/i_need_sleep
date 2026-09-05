<template>
  <RouterView v-if="route.meta.fullscreen" />
  <AppShell v-else>
    <div class="route-stage">
      <!-- 页面入场动效由 styles.css 的 .route-stage > * 挂载动画实现；
           不用 <Transition> 包裹懒加载组件（异步子组件会破坏过渡状态机，导致视图滞后一拍） -->
      <RouterView />
    </div>
  </AppShell>
</template>

<script setup>
import { useRoute } from 'vue-router'
import AppShell from './layouts/AppShell.vue'

const route = useRoute()
</script>
