<template>
  <main class="shell">
    <section class="page-hero">
      <p class="eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
      <div v-if="$slots.actions" class="actions">
        <slot name="actions" />
      </div>
    </section>
    <slot />
  </main>
</template>

<script setup>
defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, required: true }
})
</script>
