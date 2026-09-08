<template>
  <aside class="rcc" aria-label="复盘结论">
    <header class="rcc-head">
      <p class="rcc-kicker">REVIEW CONCLUSION · 结论</p>
      <h2>复盘结论</h2>
    </header>

    <!-- ===== 系统统计（自动计算，证据口径） ===== -->
    <section class="rcc-sec" aria-label="系统统计">
      <h3>系统统计<span class="rcc-sec-tag">自动生成</span></h3>
      <div v-if="metrics" class="rcc-facts" data-role="system-metrics">
        <div><dt>触发 → 首次确认</dt><dd><b>{{ formatDuration(metrics.trigger_to_confirm?.minutes) }}</b></dd></div>
        <div><dt>确认 → 开始处置</dt><dd><b>{{ formatDuration(metrics.confirm_to_start?.minutes) }}</b></dd></div>
        <div>
          <dt>总处置时长</dt>
          <dd>
            <b>{{ metrics.total_handling?.ongoing ? '进行中' : formatDuration(metrics.total_handling?.minutes) }}</b>
          </dd>
        </div>
        <div><dt>预案任务完成</dt><dd><b>{{ metrics.plan_tasks?.done ?? 0 }}/{{ metrics.plan_tasks?.total ?? 0 }}</b> 项</dd></div>
        <div><dt>模拟推送</dt><dd><b>{{ metrics.pushes?.success ?? 0 }}</b> 成功 / <b>{{ metrics.pushes?.failed ?? 0 }}</b> 失败</dd></div>
        <div><dt>是否风险升级</dt><dd :class="{ 'rcc-yes': metrics.escalated }">{{ metrics.escalated ? '是' : '否' }}</dd></div>
        <div><dt>有效恢复观测</dt><dd :class="{ 'rcc-good': metrics.valid_recovery }">{{ metrics.valid_recovery ? '有' : '无' }}</dd></div>
        <div><dt>曾进入待核实</dt><dd :class="{ 'rcc-warn': metrics.unverified_period }">{{ metrics.unverified_period ? '是' : '否' }}</dd></div>
        <div>
          <dt>重复发生（{{ metrics.recurrence?.window_days ?? 7 }} 天内同站）</dt>
          <dd><b>{{ metrics.recurrence?.count ?? 0 }}</b> 次</dd>
        </div>
      </div>
      <p v-else class="rcc-note">选中事件后展示系统统计。</p>
      <p class="rcc-note">
        口径：任务完成≠措施被证明有效；模拟推送成功≠真实送达；待核实不视为恢复。
      </p>
    </section>

    <!-- ===== 人工复盘（复盘意见，与系统证据分离） ===== -->
    <section class="rcc-sec" aria-label="人工复盘意见">
      <h3>人工复盘<span class="rcc-sec-tag rcc-sec-tag--manual">复盘意见</span></h3>
      <p v-if="!detail" class="rcc-note">选中事件后可填写复盘意见。</p>
      <template v-else>
        <p v-if="notes.version > 0" class="rcc-version" data-role="review-notes-version">
          当前第 <b>{{ notes.version }}</b> 版 ·
          {{ formatBeijing(notes.saved_at) }} 保存 · 编辑人 {{ notes.editor || '—' }}
        </p>
        <p v-else class="rcc-version">尚无复盘意见，以下填写后保存生成第 1 版。</p>

        <div class="rcc-form" data-role="review-notes-form">
          <label class="rcc-field">
            <span>事件原因或可能原因</span>
            <textarea v-model="form.cause" rows="2" placeholder="复盘意见，不与系统证据混合"></textarea>
          </label>
          <label class="rcc-field">
            <span>哪些措施有效</span>
            <textarea v-model="form.effective_measures" rows="2"></textarea>
          </label>
          <label class="rcc-field">
            <span>存在哪些问题</span>
            <textarea v-model="form.problems" rows="2"></textarea>
          </label>
          <label class="rcc-field">
            <span>是否需要调整阈值</span>
            <textarea v-model="form.threshold_adjustment" rows="2" placeholder="例如：暂不调整 / 建议下调至 8 μg/L，原因…"></textarea>
          </label>
          <label class="rcc-field">
            <span>是否需要修改预案</span>
            <textarea v-model="form.plan_adjustment" rows="2"></textarea>
          </label>

          <div class="rcc-improve">
            <div class="rcc-improve-head">
              <span>后续改进事项</span>
              <button type="button" class="rcc-mini" @click="addImprovement">+ 加一条</button>
            </div>
            <div v-for="(row, index) in form.improvements" :key="index" class="rcc-improve-row">
              <input v-model="row.item" type="text" placeholder="改进事项" aria-label="改进事项" />
              <input v-model="row.owner" type="text" placeholder="责任人" aria-label="责任人" />
              <input v-model="row.due" type="date" aria-label="完成时间" />
              <button type="button" class="rcc-mini rcc-mini--del" :aria-label="`删除改进事项 ${index + 1}`" @click="form.improvements.splice(index, 1)">删</button>
            </div>
          </div>

          <div class="rcc-save-row">
            <label class="rcc-field rcc-field--editor">
              <span>编辑人</span>
              <input v-model.trim="editor" type="text" placeholder="值班员" />
            </label>
            <button type="button" class="rcc-save" data-role="save-notes" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '保存复盘意见' }}
            </button>
          </div>
          <p v-if="saveMsg" class="rcc-save-msg" :class="{ 'rcc-save-msg--bad': saveOk === false }" role="status">{{ saveMsg }}</p>
          <p class="rcc-note">保存后生成新版本并记录编辑人与时间；历史版本仅保留最近 5 版入口。</p>
        </div>
      </template>
    </section>
  </aside>
</template>

<script setup>
// 事件复盘 · 右列：系统统计（自动）+ 人工复盘（复盘意见，单独保存、版本化）。
import { computed, reactive, ref, watch } from 'vue'
import { formatBeijing, formatDuration, saveReviewNotes } from '../../services/historyReview.js'

const props = defineProps({
  detail: { type: Object, default: null }
})

const emit = defineEmits(['saved'])

const metrics = computed(() => props.detail?.response_metrics || null)

const EMPTY_FORM = { cause: '', effective_measures: '', problems: '', threshold_adjustment: '', plan_adjustment: '', improvements: [] }

const form = reactive({ ...EMPTY_FORM, improvements: [] })
const editor = ref('')
const saving = ref(false)
const saveMsg = ref('')
const saveOk = ref(null)
const notes = ref({ version: 0, fields: {}, saved_at: null, editor: null })

watch(() => props.detail, (detail) => {
  saveMsg.value = ''
  saveOk.value = null
  const next = detail?.review_notes
  const fields = next?.fields || {}
  form.cause = fields.cause || ''
  form.effective_measures = fields.effective_measures || ''
  form.problems = fields.problems || ''
  form.threshold_adjustment = fields.threshold_adjustment || ''
  form.plan_adjustment = fields.plan_adjustment || ''
  form.improvements = (fields.improvements || []).map((row) => ({ ...row }))
  editor.value = next?.editor && next.editor !== '值班员' ? next.editor : ''
  notes.value = next || { version: 0, fields: {} }
}, { immediate: true })

function addImprovement() {
  form.improvements.push({ item: '', owner: '', due: '' })
}

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    const result = await saveReviewNotes(props.detail.event.id, { ...form }, editor.value || '值班员')
    notes.value = result
    saveOk.value = true
    saveMsg.value = `已保存为第 ${result.version} 版（编辑人 ${result.editor}）`
    emit('saved', result)
  } catch (err) {
    saveOk.value = false
    saveMsg.value = err?.message ? `保存失败：${err.message}` : '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.rcc {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.rcc-head h2 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.rcc-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.rcc-sec {
  display: grid;
  gap: 8px;
}
.rcc-sec h3 {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.rcc-sec-tag {
  font-size: 9.5px;
  font-family: var(--font-mono);
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, #4da3ff 50%, transparent);
  color: #4da3ff;
}
.rcc-sec-tag--manual {
  border-color: color-mix(in srgb, #a78bfa 55%, transparent);
  color: #a78bfa;
}
.rcc-facts {
  margin: 0;
  display: grid;
  gap: 5px;
}
.rcc-facts > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}
.rcc-facts dt {
  color: var(--text-muted);
  white-space: nowrap;
}
.rcc-facts dd {
  margin: 0;
  color: var(--text-secondary);
  text-align: right;
}
.rcc-facts b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.rcc-good {
  color: #5fd6a4 !important;
}
.rcc-warn {
  color: var(--risk-medium, #f5b45d) !important;
}
.rcc-yes {
  color: var(--risk-critical, #ef4444) !important;
}
.rcc-note {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.rcc-version {
  margin: 0;
  font-size: 10.5px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.rcc-version b {
  color: var(--text-primary);
}
.rcc-form {
  display: grid;
  gap: 8px;
}
.rcc-field {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.rcc-field span {
  font-size: 10.5px;
  color: var(--text-muted);
}
.rcc-field textarea,
.rcc-field input {
  width: 100%;
  padding: 6px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.55;
  resize: vertical;
}
.rcc-field textarea:focus-visible,
.rcc-field input:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rcc-improve {
  display: grid;
  gap: 5px;
}
.rcc-improve-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10.5px;
  color: var(--text-muted);
}
.rcc-improve-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) 128px auto;
  gap: 4px;
}
.rcc-mini {
  appearance: none;
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}
.rcc-mini:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rcc-mini--del {
  color: var(--risk-critical, #ef4444);
}
.rcc-save-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.rcc-field--editor {
  flex: 1 1 120px;
}
.rcc-save {
  appearance: none;
  min-height: 34px;
  padding: 4px 16px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.rcc-save:disabled {
  opacity: 0.6;
  cursor: wait;
}
.rcc-save:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rcc-save-msg {
  margin: 0;
  font-size: 11px;
  color: #5fd6a4;
}
.rcc-save-msg--bad {
  color: var(--risk-critical, #ef4444);
}
</style>
