<template>
  <div class="route-stage">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in" appear>
        <component :is="Component" />
      </Transition>
    </RouterView>
  </div>
</template>