<template>
  <main class="notfound">
    <p class="nf-code">404</p>
    <h1 class="nf-title">页面不存在</h1>
    <p class="nf-note">
      当前地址没有对应页面。正式功能仅提供：首页、综合驾驶舱、监测站点研判、时空推演、历史复盘。
    </p>
    <div class="nf-actions">
      <RouterLink v-if="backPath" class="nf-btn nf-btn-solid" :to="backPath">
        ← 返回上一业务页面
      </RouterLink>
      <RouterLink class="nf-btn nf-btn-solid" to="/">回到首页</RouterLink>
      <RouterLink class="nf-btn nf-btn-ghost" to="/cockpit">进入驾驶舱</RouterLink>
    </div>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import { routeUi } from '../stores/routeUi.js'

// “返回上一业务页面”只在确认存在站内来源时出现，且使用确定性路由（非 history.back）
const backPath = computed(() => routeUi.lastBusinessPath || '')
</script>

<style scoped>
.notfound {
  flex: 1;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 14px;
  padding: 48px 20px;
  text-align: center;
}

.nf-code {
  margin: 0;
  color: var(--color-primary);
  font-family: var(--font-mono);
  font-size: 64px;
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1;
}

.nf-title {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 26px;
}

.nf-note {
  margin: 0;
  max-width: 34rem;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.8;
}

.nf-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  margin-top: 8px;
}

.nf-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 0 22px;
  border-radius: var(--radius-item);
  font-size: 14px;
  font-weight: 600;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.nf-btn-solid {
  border: 1px solid var(--border-strong);
  background: var(--color-primary);
  color: var(--color-primary-ink);
}
.nf-btn-solid:hover { filter: brightness(1.08); }
.nf-btn-ghost {
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.nf-btn-ghost:hover {
  color: var(--color-primary);
  border-color: var(--border-strong);
}
</style>
