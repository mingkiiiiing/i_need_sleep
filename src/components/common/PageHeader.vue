<template>
  <header class="page-header">
    <p v-if="sectionNo || eyebrow" class="ph-eyebrow">
      <span v-if="sectionNo" class="ph-no">{{ sectionNo }}</span>
      <span v-if="eyebrow" class="ph-eyebrow-text">{{ eyebrow }}</span>
    </p>
    <h1 class="ph-title">{{ title }}</h1>
    <p v-if="description" class="ph-desc">{{ description }}</p>
    <div v-if="$slots.meta" class="ph-meta">
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="ph-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  sectionNo: { type: String, default: '' },
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, default: '' }
})
</script>

<style scoped>
.page-header {
  display: grid;
  gap: 10px;
  margin-bottom: var(--spacing-5);
}
.ph-eyebrow {
  display: inline-flex;
  align-items: baseline;
  gap: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.ph-no { color: var(--color-primary); }
.ph-title {
  font-family: var(--font-display);
  font-size: clamp(22px, 2.6vw, 30px);
  font-weight: 700;
  letter-spacing: 0.3px;
  line-height: 1.2;
  color: var(--text-primary);
}
.ph-desc {
  max-width: 72ch;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--text-secondary);
}
.ph-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.ph-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
</style>
