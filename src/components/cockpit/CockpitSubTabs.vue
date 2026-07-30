<template>
  <nav class="sub-tabs" aria-label="驾驶舱子页面切换">
    <RouterLink
      v-for="t in tabs"
      :key="t.to"
      :to="t.to"
      class="sub-tab"
      :class="{ active: isActive(t) }"
    >
      <span class="sub-tab-num">{{ t.num }}</span>
      <span class="sub-tab-label">{{ t.label }}</span>
    </RouterLink>
  </nav>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const tabs = [
  { to: '/stations', num: '01', label: '监测站档位研判', match: ['/stations'] },
  { to: '/heatmap',  num: '02', label: '风险热力分区',     match: ['/heatmap']  },
  { to: '/history',  num: '03', label: '历史事件回放',     match: ['/history']  }
]

const route = useRoute()
const currentPath = computed(() => route.path)
function isActive(t) { return t.match.includes(currentPath.value) }
</script>

<style scoped>
.sub-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 28px;
  padding: 10px;
  border-radius: 14px;
  background: rgba(8, 16, 28, 0.5);
  border: 1px solid var(--panel-line);
}
.sub-tab {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-radius: 999px;
  background: transparent;
  color: var(--text-soft);
  font-size: 13px;
  letter-spacing: 0.02em;
  border: 1px solid transparent;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
  text-decoration: none;
}
.sub-tab:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text);
}
.sub-tab-num {
  display: inline-block;
  min-width: 28px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  background: rgba(34, 211, 197, 0.16);
  color: var(--teal);
  border: 1px solid rgba(34, 211, 197, 0.28);
}
.sub-tab.active {
  background: linear-gradient(135deg, rgba(34, 211, 197, 0.22), rgba(34, 211, 197, 0.08));
  color: var(--text);
  border-color: rgba(34, 211, 197, 0.45);
}
.sub-tab.active .sub-tab-num {
  background: var(--teal);
  color: #02141c;
  border-color: var(--teal);
}
</style>
