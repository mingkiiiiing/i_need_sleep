<template>
  <main class="hero-shell-shell">
    <header class="hero-header" :class="{ in: ready }">
      <div class="hero-header-left">
        <p class="hero-eyebrow">
          <span class="hero-eyebrow-num">{{ sectionNo }}</span>
          <span class="hero-eyebrow-rule"></span>
          <span class="hero-eyebrow-label">{{ eyebrow }}</span>
        </p>
        <h1 class="hero-page-title">{{ title }}</h1>
        <p class="hero-page-desc">{{ description }}</p>
      </div>

      <aside class="hero-meta-grid" v-if="$slots.meta">
        <slot name="meta" />
      </aside>
    </header>

    <section class="hero-body" :class="{ in: ready }">
      <slot />
    </section>

    <footer v-if="$slots.actions" class="hero-actions">
      <slot name="actions" />
    </footer>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'

defineProps({
  sectionNo: { type: String, default: '01 / 04' },
  eyebrow: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, default: '' }
})

const ready = ref(false)
onMounted(() => {
  requestAnimationFrame(() => {
    ready.value = true
  })
})
</script>

<style scoped>
.hero-shell-shell {
  max-width: 1480px;
  margin: 0 auto;
  padding: 28px 36px 60px;
  position: relative;
}

.hero-header {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 48px;
  align-items: end;
  margin-bottom: 32px;
  padding: 28px 32px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  box-shadow: var(--glass-shadow), inset 0 1px 0 var(--glass-highlight);
  opacity: 0;
  transform: translateY(20px);
  transition: opacity .9s ease, transform .9s ease;
}
.hero-header.in { opacity: 1; transform: none; }

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin: 0 0 16px;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 12px;
  letter-spacing: 4px;
  color: var(--teal);
  font-weight: 700;
}
.hero-eyebrow-num { color: var(--text); }
.hero-eyebrow-rule {
  display: inline-block;
  width: 56px;
  height: 1px;
  background: linear-gradient(90deg, var(--teal), transparent);
}
.hero-eyebrow-label { color: var(--muted); }

.hero-page-title {
  margin: 0 0 18px;
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: clamp(34px, 4.4vw, 58px);
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.01em;
  color: var(--text);
}
.hero-page-desc {
  max-width: 720px;
  margin: 0;
  color: var(--text-soft);
  font-size: 15.5px;
  line-height: 1.85;
}

.hero-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-self: stretch;
}

.hero-body {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity .9s ease .12s, transform .9s ease .12s;
}
.hero-body.in { opacity: 1; transform: none; }

.hero-actions {
  margin-top: 28px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

@media (max-width: 1080px) {
  .hero-header { grid-template-columns: 1fr; gap: 24px; }
  .hero-meta-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .hero-shell-shell { padding: 18px; }
  .hero-meta-grid { grid-template-columns: 1fr; }
}
</style>