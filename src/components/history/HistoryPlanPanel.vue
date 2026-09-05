<template>
  <section class="hpl" data-role="plan-panel" aria-label="推荐预案能力状态">
    <header class="hpl-head">
      <div>
        <p class="hpl-kicker">PLAYBOOK · 预案能力</p>
        <h3>推荐预案（规划中模板）</h3>
      </div>
      <p class="hpl-note" data-role="plan-capability-note">{{ PLAN_CAPABILITY_NOTE }}</p>
    </header>

    <div class="hpl-grid">
      <article v-for="tpl in PLAN_TEMPLATES" :key="tpl.id" class="hpl-card" data-role="plan-template">
        <h4>{{ tpl.name }}</h4>
        <p>{{ tpl.note }}</p>
        <ul class="hpl-blank">
          <li>适配分：无（未执行自动匹配）</li>
          <li>负责人：无</li>
          <li>措施状态：无</li>
        </ul>
      </article>
    </div>

    <div class="hpl-foot">
      <button
        type="button"
        class="hpl-match-btn"
        data-role="plan-match"
        disabled
        aria-disabled="true"
        title="预案匹配接口未实现，不能产生前端固定适配分"
      >匹配预案 · 接口未接入</button>
      <p class="hpl-foot-note">「匹配预案」需后端提供预案库与匹配算法后开放；当前按钮不产生任何匹配结果。</p>
    </div>

    <div class="hpl-caps" data-role="plan-caps">
      <h4>能力状态</h4>
      <StatePanel
        v-if="capsState === 'loading'"
        state="loading"
        title="能力状态查询中…"
      />
      <StatePanel
        v-else-if="capsState === 'error'"
        state="error"
        title="能力状态查询失败"
        description="/forecast-capabilities 请求失败，不推测各通道可用性。"
      >
        <button type="button" class="hpl-retry" data-role="caps-retry" @click="$emit('retry-caps')">重试查询</button>
      </StatePanel>
      <dl v-else-if="capRows.length" class="hpl-caps-list" data-role="caps-list">
        <div v-for="row in capRows" :key="row.key">
          <dt>{{ row.label }}</dt>
          <dd><span class="hpl-caps-code">{{ row.value }}</span></dd>
        </div>
      </dl>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import { PLAN_TEMPLATES, PLAN_CAPABILITY_NOTE } from './historyCore.js'

const props = defineProps({
  capabilities: { type: Object, default: null },
  capsState: { type: String, default: 'loading' }
})

defineEmits(['retry-caps'])

const CAP_ROWS = [
  { key: 'real_time_warning_dispatch', label: '真实预警发布' },
  { key: 'demo_warning_dispatch', label: '演示预警发送' },
  { key: 'historical_observation', label: '历史真实观测' },
  { key: 'short_term_forecast_1_3d', label: '短临预测 1—3 天' }
]

const capRows = computed(() => {
  const caps = props.capabilities
  if (!caps || typeof caps !== 'object') return []
  return CAP_ROWS
    .filter((row) => typeof caps[row.key] === 'string')
    .map((row) => ({ ...row, value: caps[row.key] }))
})
</script>

<style scoped>
.hpl {
  display: grid;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.hpl-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.hpl-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.hpl-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.hpl-note {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--risk-medium, #facc15);
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #facc15) 45%, transparent);
  border-radius: 999px;
  padding: 4px 12px;
}
.hpl-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.hpl-card {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  min-width: 0;
}
.hpl-card h4 {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-primary);
}
.hpl-card p {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.hpl-blank {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.hpl-blank li {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.hpl-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hpl-match-btn {
  appearance: none;
  min-height: 44px;
  padding: 6px 18px;
  border: 1px dashed var(--border-subtle);
  border-radius: 9px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 650;
  cursor: not-allowed;
}
.hpl-match-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hpl-foot-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}
.hpl-caps {
  display: grid;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-subtle);
}
.hpl-caps h4 {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-secondary);
}
.hpl-caps-list {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 16px;
}
.hpl-caps-list > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.hpl-caps-list dt {
  font-size: 11px;
  color: var(--text-muted);
}
.hpl-caps-list dd {
  margin: 0;
  min-width: 0;
}
.hpl-caps-code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-secondary);
  word-break: break-all;
}
.hpl-retry {
  appearance: none;
  min-height: 34px;
  padding: 4px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.hpl-retry:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

@media (max-width: 960px) {
  .hpl-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .hpl-caps-list {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
