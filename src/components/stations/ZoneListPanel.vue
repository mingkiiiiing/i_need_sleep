<template>
  <section class="stn-block stn-list-panel" aria-label="分区搜索、筛选与列表">
    <header class="stn-sec-head">
      <h2>演示分区</h2>
      <span class="stn-sec-tag">共 {{ rows.length }} 个 · 按当前档位风险排序</span>
    </header>

    <div class="stn-search-row">
      <div class="stn-search">
        <input
          v-model="searchInput"
          type="search"
          aria-label="搜索演示分区编号或名称"
          placeholder="搜索编号 / 名称，如 NW-01"
          @input="emitSearch"
        />
        <button
          v-if="searchInput"
          type="button"
          class="stn-search-clear"
          aria-label="清除搜索"
          @click="clearSearch"
        >×</button>
      </div>
    </div>

    <div class="stn-filter" role="group" aria-label="风险筛选">
      <button
        v-for="opt in filterOptions"
        :key="opt.value"
        type="button"
        :aria-pressed="String(filter === opt.value)"
        :class="{ active: filter === opt.value }"
        @click="$emit('update:filter', opt.value)"
      >{{ opt.label }}</button>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" role="status" aria-label="分区列表加载中">
      <div v-for="i in 6" :key="i" class="skel-row"></div>
    </div>

    <StatePanel
      v-else-if="state === 'error'"
      state="error"
      title="分区列表加载失败"
      description="演示分区接口请求失败，可重试加载。"
    >
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </StatePanel>

    <div v-else-if="rows.length" class="stn-zone-list">
      <div v-for="row in rows" :key="row.id" role="listitem">
        <button
          type="button"
          class="stn-zone-item"
          :class="{ selected: row.id === selectedId }"
          :aria-current="row.id === selectedId ? 'true' : undefined"
          :data-zone-id="row.id"
          @click="$emit('select', row.id)"
        >
          <span class="zi-rank">{{ String(row.rank).padStart(2, '0') }}</span>
          <span class="zi-main">
            <span class="zi-code">{{ row.short }}</span>
            <span class="zi-name">{{ row.name }}</span>
          </span>
          <span class="zi-side">
            <span class="zi-risk" :class="`lv-${row.riskClass}`">{{ row.riskText }}</span>
            <span class="zi-score">{{ row.score == null ? '—' : row.score }}</span>
          </span>
        </button>
      </div>
    </div>

    <div v-else class="stn-list-empty">
      <p class="sle-title">未找到匹配的演示分区</p>
      <p class="sle-desc">当前搜索或筛选条件下没有分区。可调整关键词，或清除全部条件。</p>
      <button type="button" class="stn-inline-btn" @click="$emit('reset-filters')">清除搜索和筛选</button>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import StatePanel from '../common/StatePanel.vue'

defineProps({
  rows: { type: Array, default: () => [] }, // 已由父级完成搜索/筛选过滤与排名
  selectedId: { type: String, default: '' },
  state: { type: String, default: 'loading' }, // loading | error | ok
  filter: { type: String, default: 'all' } // all | high | mid | low（父级持有，用于 aria-pressed/active）
})

const emit = defineEmits(['update:search', 'update:filter', 'select', 'retry', 'reset-filters'])

const filterOptions = [
  { value: 'all', label: '全部' },
  { value: 'high', label: '高风险' },
  { value: 'mid', label: '中风险' },
  { value: 'low', label: '低风险' }
]

const searchInput = ref('')

let debounceTimer = null
function emitSearch() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    emit('update:search', searchInput.value.trim())
  }, 300)
}

function clearSearch() {
  clearTimeout(debounceTimer)
  searchInput.value = ''
  emit('update:search', '')
}

</script>
