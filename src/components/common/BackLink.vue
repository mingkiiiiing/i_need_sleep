<template>
  <RouterLink class="back-link" :to="to">
    <span class="bl-arrow" aria-hidden="true">←</span>
    <span>{{ label }}</span>
  </RouterLink>
</template>

<script setup>
// 返回链接走确定性路由（由调用方显式传入 to），不依赖 history.back()
defineProps({
  to: { type: [String, Object], default: '/' },
  label: { type: String, default: '返回' }
})
</script>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.back-link:hover {
  color: var(--color-primary);
  border-color: var(--border-strong);
}
.bl-arrow {
  font-family: var(--font-mono);
}
</style>
