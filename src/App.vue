<template>
  <GlobalNav />
  <div class="route-stage">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in" appear>
        <component :is="Component" />
      </Transition>
    </RouterView>
  </div>
</template>

<script setup>
import GlobalNav from './components/GlobalNav.vue'
</script>
