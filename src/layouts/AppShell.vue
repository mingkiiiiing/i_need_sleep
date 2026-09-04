<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主内容</a>

    <AppSidebar :open="sidebarOpen" />
    <div v-if="sidebarOpen" class="sidebar-mask" aria-hidden="true" @click="sidebarOpen = false"></div>

    <div class="app-main">
      <AppTopBar ref="topBarRef" :open="sidebarOpen" @toggle-sidebar="toggleSidebar" />
      <DataContextBar />

      <div v-if="!routeUi.errorPath" id="main-content" class="app-content" tabindex="-1">
        <slot />
      </div>
      <div v-else id="main-content" class="app-content app-content--error" tabindex="-1">
        <StatePanel
          state="error"
          title="页面加载失败"
          :description="`「${routeUi.errorPath}」的资源加载出现问题，可重试或返回首页。`"
        >
          <button type="button" class="shell-btn" @click="retry">重试加载</button>
          <RouterLink class="shell-btn shell-btn--ghost" to="/">回到首页</RouterLink>
        </StatePanel>
      </div>
    </div>

    <div v-if="routeUi.loading" class="route-progress" role="progressbar" aria-label="页面资源加载中">
      <span class="route-progress-fill"></span>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar from '../components/common/AppSidebar.vue'
import AppTopBar from '../components/common/AppTopBar.vue'
import DataContextBar from '../components/common/DataContextBar.vue'
import StatePanel from '../components/common/StatePanel.vue'
import { routeUi } from '../stores/routeUi.js'

const route = useRoute()
const router = useRouter()
const sidebarOpen = ref(false)
const topBarRef = ref(null)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

// 抽屉关闭后把焦点还给汉堡按钮（仅移动抽屉形态）
function focusMenuButton() {
  if (!window.matchMedia('(max-width: 960px)').matches) return
  topBarRef.value?.menuButton?.focus?.()
}

watch(
  () => route.fullPath,
  () => {
    sidebarOpen.value = false
    routeUi.errorPath = ''
  }
)

watch(sidebarOpen, (now, before) => {
  if (before && !now) focusMenuButton()
})

function retry() {
  const target = routeUi.errorPath
  routeUi.errorPath = ''
  router.replace(target || '/')
}

function onKeydown(e) {
  if (e.key === 'Escape') sidebarOpen.value = false
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.app-main {
  margin-left: 72px;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  outline: none;
}
.app-content--error {
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
}
.app-content--error :deep(.state-panel) {
  width: min(560px, 100%);
}

.shell-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 0 18px;
  border: none;
  border-radius: var(--radius-item);
  background: var(--color-primary);
  color: var(--color-primary-ink);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: filter 0.15s ease;
}
.shell-btn:hover { filter: brightness(1.08); }
.shell-btn--ghost {
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}

.skip-link {
  position: fixed;
  top: -60px;
  left: 84px;
  z-index: 2000;
  padding: 12px 18px;
  border-radius: var(--radius-item);
  background: var(--color-primary);
  color: var(--color-primary-ink);
  font-size: 13px;
  font-weight: 700;
  transition: top 0.2s ease;
}
.skip-link:focus-visible { top: 12px; }

.sidebar-mask {
  position: fixed;
  inset: 0;
  z-index: 1150;
  background: rgba(2, 8, 18, 0.55);
  animation: mask-fade-in 0.2s ease both;
}
@keyframes mask-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@media (min-width: 961px) {
  .sidebar-mask { display: none; }
}

.route-progress {
  position: fixed;
  top: 0;
  left: 72px;
  right: 0;
  height: 2px;
  z-index: 1700;
  overflow: hidden;
}
.route-progress-fill {
  display: block;
  height: 100%;
  width: 40%;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, var(--color-primary), var(--color-secondary));
  animation: route-progress-slide 1.1s ease-in-out infinite;
}
@keyframes route-progress-slide {
  from { transform: translateX(-110%); }
  to { transform: translateX(360%); }
}

@media (max-width: 960px) {
  .app-main { margin-left: 0; }
  .route-progress { left: 0; }
  .skip-link { left: 12px; }
}
</style>
