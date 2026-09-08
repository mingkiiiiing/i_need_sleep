<template>
  <main class="page-ac">
    <header class="ac-head">
      <div class="ac-title">
        <p class="ac-kicker">ALERT CENTER · REALTIME + FORECAST</p>
        <h1>预警与应急预案中心</h1>
      </div>
      <div class="ac-head-actions">
        <DataModeBadge mode="observed" label="实时观测" />
        <button type="button" class="ac-btn" :disabled="evaluating" @click="runEvaluate">
          {{ evaluating ? '巡检中…' : '立即巡检' }}
        </button>
        <button type="button" class="ac-btn" @click="rulesOpen = true">规则配置</button>
        <button type="button" class="ac-btn" @click="plansOpen = true">预案库</button>
      </div>
    </header>

    <!-- 顶部统计 -->
    <section class="ac-stats" aria-label="预警统计">
      <div class="ac-stat">
        <strong>{{ stats.pending?.total ?? '—' }}<small>条</small></strong>
        <span>待确认</span>
        <small class="ac-stat-sub">实时 {{ stats.pending?.realtime ?? 0 }} · 预测 {{ stats.pending?.predicted ?? 0 }}</small>
      </div>
      <div class="ac-stat">
        <strong>{{ stats.processing ?? '—' }}<small>条</small></strong>
        <span>处理中</span>
        <small class="ac-stat-sub">已确认 + 处置中</small>
      </div>
      <div class="ac-stat">
        <strong>{{ stats.closed_today ?? '—' }}<small>条</small></strong>
        <span>今日关闭</span>
        <small class="ac-stat-sub">按关闭时间（北京时间）统计</small>
      </div>
      <div class="ac-stat">
        <strong>{{ stats.avg_response_min != null ? stats.avg_response_min : '—' }}<small v-if="stats.avg_response_min != null">分钟</small></strong>
        <span>平均响应时间</span>
        <small class="ac-stat-sub">触发→首次确认 · 样本 {{ stats.response_samples ?? 0 }}</small>
      </div>
    </section>

    <div v-if="state === 'error'" class="ac-error" role="alert">
      预警中心加载失败（不会回退情景数据）
      <button type="button" class="ac-btn" @click="load(true)">重试</button>
    </div>
    <div v-else-if="state === 'loading'" class="ac-loading">正在加载预警中心…</div>

    <template v-else>
      <div class="ac-grid">
        <!-- 左：事件列表 -->
        <aside class="ac-col ac-list" aria-label="预警事件列表">
          <div class="ac-tabs" role="tablist" aria-label="预警类型">
            <button
              v-for="t in typeTabs" :key="t.value" type="button" role="tab"
              class="ac-tab" :class="{ 'ac-tab--on': typeTab === t.value }"
              :aria-selected="String(typeTab === t.value)"
              @click="typeTab = t.value"
            >{{ t.label }}</button>
          </div>
          <div class="ac-list-tools">
            <select v-model="statusFilter" class="ac-select" aria-label="处理状态筛选">
              <option value="all">全部状态</option>
              <option v-for="(label, key) in EVENT_STATUS_TEXT" :key="key" :value="key">{{ label }}</option>
            </select>
            <input v-model.trim="search" type="search" class="ac-input" placeholder="搜索站点 / 编号" aria-label="搜索站点或编号" />
          </div>

          <p v-if="typeTab === 'predicted' && !events.length" class="ac-empty">
            预测预警尚未接入：时空推演预测批次输出后，符合规则的未来风险会在此生成事件（可在"规则配置"中设置概率门槛）。当前不伪造预测数据。
          </p>
          <p v-else-if="!events.length" class="ac-empty">暂无符合条件的事件。</p>

          <ul v-else class="ac-events">
            <li v-for="e in events" :key="e.id">
              <button
                type="button"
                class="ac-event"
                :class="{ 'ac-event--on': e.id === selectedId, [`ac-event--${e.level}`]: true }"
                @click="selectEvent(e.id)"
              >
                <span class="ac-event-row">
                  <span class="ac-chip" :class="`ac-chip--type`">{{ EVENT_TYPE_TEXT[e.type] || e.type }}</span>
                  <span class="ac-chip" :class="`ac-chip--${e.level}`">{{ levelText(e.level) }}</span>
                  <strong class="ac-event-name">{{ e.station_name }}</strong>
                  <span class="ac-event-status" :class="`ac-event-status--${e.status}`">{{ EVENT_STATUS_TEXT[e.status] }}</span>
                </span>
                <span class="ac-event-row ac-event-title">{{ e.title }}</span>
                <span class="ac-event-row ac-event-meta">
                  <span>{{ e.evidence_state === 'unverified' ? '数据待核实' : e.evidence_state === 'recovered' ? '指标已恢复' : fmtClock(e.created_at) }}</span>
                  <span>{{ e.assignee || '待指派' }}</span>
                </span>
              </button>
            </li>
          </ul>
        </aside>

        <!-- 中：事件详情 -->
        <section class="ac-col ac-detail" aria-label="当前预警详情">
          <p v-if="!detail" class="ac-empty">从左侧选择一条预警事件查看详情与处置操作。</p>
          <template v-else>
            <div class="ac-detail-head">
              <h2>{{ detail.title }}</h2>
              <div class="ac-detail-chips">
                <span class="ac-chip ac-chip--type">{{ EVENT_TYPE_TEXT[detail.type] }}预警</span>
                <span class="ac-chip" :class="`ac-chip--${detail.level}`">{{ levelText(detail.level) }}</span>
                <span class="ac-chip" :class="`ac-chip--st-${detail.status}`">{{ EVENT_STATUS_TEXT[detail.status] }}</span>
                <span class="ac-chip ac-chip--mono">{{ detail.no }}</span>
              </div>
            </div>

            <div class="ac-tabs" role="tablist" aria-label="详情视图">
              <button type="button" role="tab" class="ac-tab" :class="{ 'ac-tab--on': detailTab === 'info' }" :aria-selected="String(detailTab === 'info')" @click="detailTab = 'info'">预警详情</button>
              <button type="button" role="tab" class="ac-tab" :class="{ 'ac-tab--on': detailTab === 'trend' }" :aria-selected="String(detailTab === 'trend')" @click="detailTab = 'trend'">趋势分析</button>
            </div>

            <template v-if="detailTab === 'info'">
              <div v-if="detail.evidence.state === 'unverified'" class="ac-note ac-note--warn" role="status">
                站点暂未出现在最新快照中：数据待核实，不视为指标恢复。
              </div>
              <div v-else-if="detail.evidence.state === 'recovered'" class="ac-note ac-note--ok" role="status">
                指标已恢复至阈值以下：请复核处置结果后关闭，系统不会自动完成任务。
              </div>

              <dl class="ac-facts">
                <div><dt>当前{{ detail.evidence.indicator }}</dt><dd><b>{{ detail.evidence.value != null ? detail.evidence.value : '—' }}</b> {{ detail.evidence.unit }}</dd></div>
                <div><dt>触发阈值</dt><dd>≥ {{ detail.evidence.threshold }} {{ detail.evidence.unit }}</dd></div>
                <div><dt>观测时间</dt><dd class="ac-mono">{{ fmtTime(detail.evidence.observed_at) }}</dd></div>
                <div><dt>触发时间</dt><dd class="ac-mono">{{ fmtTime(detail.evidence.triggered_at || detail.created_at) }}</dd></div>
                <div><dt>证据状态</dt><dd><span class="ac-chip" :class="`ac-chip--ev-${detail.evidence.state}`">{{ EVIDENCE_STATE_TEXT[detail.evidence.state] || detail.evidence.state }}</span></dd></div>
                <div><dt>触发规则</dt><dd>{{ detail.evidence.rule_name }}</dd></div>
              </dl>

              <!-- 处置流程 -->
              <div class="ac-flow" aria-label="处置流程">
                <template v-for="(step, i) in FLOW_STEPS" :key="step">
                  <span class="ac-flow-step" :class="flowState(step)">
                    <i>{{ i + 1 }}</i>
                    <em>{{ EVENT_STATUS_TEXT[step] }}</em>
                  </span>
                  <span v-if="i < FLOW_STEPS.length - 1" class="ac-flow-line" :class="{ 'ac-flow-line--done': flowState(FLOW_STEPS[i + 1]) !== '' }"></span>
                </template>
              </div>

              <!-- 操作区 -->
              <div v-if="opError" class="ac-note ac-note--warn" role="alert">{{ opError }}</div>
              <div class="ac-actions" aria-label="处置操作">
                <button
                  v-for="a in availableActions" :key="a.action"
                  type="button" class="ac-btn" :class="{ 'ac-btn--primary': a.kind === 'primary' }"
                  @click="openAction(a)"
                >{{ a.label }}</button>
                <button
                  v-if="detail.type === 'realtime' && detail.status !== 'closed' && detail.status !== 'revoked'"
                  type="button" class="ac-btn" @click="pushOpen = true"
                >模拟推送</button>
                <a v-if="detail.station_id" class="ac-link" :href="`#/stations?p=${detail.station_id}`">查看监测站 →</a>
              </div>
              <p class="ac-assignee">负责人：{{ detail.assignee || '待指派' }}</p>

              <!-- 该站最新观测（真实数据，缺测如实显示） -->
              <div v-if="detail.type === 'realtime'" class="ac-sec">
                <h4>该站最新观测 <span class="ac-sec-tag">{{ fmtTime(latestObservedAt) }}</span></h4>
                <div v-if="latestObs.length" class="ac-latest-grid">
                  <div v-for="row in latestObs" :key="row.code" class="ac-latest-item">
                    <span class="ac-latest-k">{{ row.label }}</span>
                    <span class="ac-latest-v">
                      <b>{{ row.value }}</b><small v-if="row.unit"> {{ row.unit }}</small>
                    </span>
                    <span class="ac-flag" :class="`ac-flag--${row.tone}`">{{ row.flag }}</span>
                  </div>
                </div>
                <p v-else class="ac-sec-empty">{{ latestState === 'loading' ? '正在读取该站观测…' : '该站暂无有效观测。' }}</p>
              </div>

              <!-- 处理动态（本事件的时间线） -->
              <div class="ac-sec">
                <h4>处理动态 <span class="ac-sec-tag">{{ detail.records.length }} 条</span></h4>
                <ul class="ac-timeline">
                  <li v-for="(r, i) in detailTimeline" :key="i" class="ac-tl-row">
                    <span class="ac-mono ac-tl-time">{{ fmtTime(r.at) }}</span>
                    <span class="ac-tl-main"><b>{{ RECORD_ACTION_TEXT[r.action] || r.action }}</b> · {{ r.detail }}</span>
                    <span class="ac-tl-actor">{{ r.actor }}</span>
                  </li>
                </ul>
                <button v-if="detail.records.length > 4" type="button" class="ac-tl-more" @click="timelineExpanded = !timelineExpanded">
                  {{ timelineExpanded ? '收起' : `展开全部 ${detail.records.length} 条` }}
                </button>
              </div>

              <!-- 已采用预案的任务 -->
              <div v-if="detail.plan" class="ac-plan-run">
                <h3>已采用预案：{{ detail.plan.name }}（{{ detail.plan.version }}）</h3>
                <p class="ac-plan-meta">采用于 {{ fmtTime(detail.plan.adopted_at) }} · 已完成 {{ doneTasks }}/{{ detail.plan.tasks.length }} 项（预案库更新不影响已生成任务）</p>
                <ul class="ac-tasks">
                  <li v-for="t in detail.plan.tasks" :key="t.id" class="ac-task">
                    <span class="ac-task-main">
                      <strong>{{ t.text }}</strong>
                      <small>{{ groupName(t.group) }}<template v-if="t.due"> · {{ t.due }}</template><template v-if="t.note"> · {{ t.note }}</template></small>
                    </span>
                    <select
                      class="ac-select ac-select--sm" :value="t.status"
                      :aria-label="`任务状态：${t.text}`"
                      @change="updateTask(t, $event.target.value)"
                    >
                      <option value="todo">待开始</option>
                      <option value="doing">进行中</option>
                      <option value="done">已完成</option>
                    </select>
                  </li>
                </ul>
              </div>
            </template>

            <!-- 趋势分析 -->
            <template v-else>
              <div v-if="detail.type !== 'realtime'" class="ac-empty">预测趋势将随预测批次一并展示（当前尚未接入预测数据源）。</div>
              <div v-else-if="trendState === 'loading'" class="ac-empty">正在读取该站观测…</div>
              <div v-else-if="trendState === 'error'" class="ac-empty">观测读取失败，请稍后重试。</div>
              <div v-else-if="trendPoints.length < 2" class="ac-empty">该站可用叶绿素a观测不足两个快照点，暂无可绘制趋势。</div>
              <div v-else class="ac-trend">
                <svg viewBox="0 0 600 200" preserveAspectRatio="none" role="img" aria-label="叶绿素a 观测趋势与阈值">
                  <line class="ac-grid" x1="0" :y1="yFor(10)" :x2="600" :y2="yFor(10)" />
                  <line class="ac-grid ac-grid--moderate" x1="0" :y1="yFor(25)" :x2="600" :y2="yFor(25)" />
                  <text class="ac-grid-label" :x="598" :y="yFor(10) - 4" text-anchor="end">黄色阈值 10</text>
                  <text class="ac-grid-label ac-grid-label--moderate" :x="598" :y="yFor(25) - 4" text-anchor="end">红色阈值 25</text>
                  <line v-if="triggerX != null" class="ac-trigger-line" :x1="triggerX" :y1="0" :x2="triggerX" :y2="200" />
                  <polyline class="ac-trend-line" :points="trendPolyline" />
                  <circle v-for="(p, i) in trendPoints" :key="i" class="ac-trend-dot" :cx="p.x" :cy="p.y" r="2.6" />
                </svg>
                <div class="ac-trend-axis">
                  <span>{{ trendPoints[0].t }}</span>
                  <span>实测累计 · {{ trendPoints.length }} 个快照 · 缺测不插值</span>
                  <span>{{ trendPoints[trendPoints.length - 1].t }}</span>
                </div>
              </div>
            </template>
          </template>
        </section>

        <!-- 右：应急预案 -->
        <section class="ac-col ac-plan" aria-label="匹配应急预案">
          <template v-if="detail">
            <template v-if="detail.plan">
              <div class="ac-plan-head">
                <h3>执行中预案</h3>
                <span class="ac-chip ac-chip--ok">已采用</span>
              </div>
              <p class="ac-plan-name">{{ detail.plan.name }}</p>
              <p class="ac-plan-meta">{{ detail.plan.department }} · 版本 {{ detail.plan.version }}</p>
            </template>
            <template v-else-if="detail.matched_plan">
              <div class="ac-plan-head">
                <h3>推荐预案</h3>
              </div>
              <p class="ac-plan-name">{{ detail.matched_plan.name }}</p>
              <p class="ac-plan-meta">{{ detail.matched_plan.department }} · 版本 {{ detail.matched_plan.version }}</p>
              <div class="ac-plan-reasons">
                <p>匹配依据</p>
                <ul>
                  <li v-for="r in detail.matched_plan.match_reasons" :key="r">{{ r }}</li>
                </ul>
              </div>
              <p class="ac-plan-measures-title">建议措施（{{ detail.matched_plan.measures.length }} 项）</p>
              <ul class="ac-plan-measures">
                <li v-for="m in detail.matched_plan.measures" :key="m.text">
                  <span>{{ m.text }}</span>
                  <small>{{ groupName(m.group) }}</small>
                </li>
              </ul>
              <button
                type="button" class="ac-btn ac-btn--primary ac-btn--wide"
                :disabled="!canAdoptPlan || adopting"
                @click="adoptPlan(detail.matched_plan.plan_id)"
              >{{ adopting ? '采用中…' : canAdoptPlan ? '采用预案' : '确认预警后可采用' }}</button>
            </template>
            <template v-else>
              <p class="ac-empty">暂无适用预案，可在预案库中人工选择并记录原因。</p>
            </template>
            <p class="ac-plan-note">预案更新时间以预案库为准；采用后任务独立留存。</p>
          </template>
          <p v-else class="ac-empty">选择事件后展示匹配的应急预案。</p>
        </section>
      </div>

      <!-- 底部：处理记录 / 模拟推送记录 / 操作日志 -->
      <section class="ac-records" aria-label="处理与推送记录">
        <div class="ac-tabs" role="tablist" aria-label="记录类型">
          <button v-for="t in recordTabs" :key="t.value" type="button" role="tab" class="ac-tab" :class="{ 'ac-tab--on': recordTab === t.value }" :aria-selected="String(recordTab === t.value)" @click="recordTab = t.value">{{ t.label }}</button>
          <button type="button" class="ac-records-expand" @click="recordsExpanded = !recordsExpanded">{{ recordsExpanded ? '收起' : '展开全部' }}</button>
        </div>
        <p v-if="!recordRows.length" class="ac-empty">暂无记录。</p>
        <ul v-else class="ac-record-list">
          <li v-for="(r, i) in visibleRecords" :key="i" class="ac-record">
            <span class="ac-mono ac-record-time">{{ fmtTime(r.at) }}</span>
            <span class="ac-record-main">{{ recordMain(r) }}</span>
            <span class="ac-record-actor">{{ r.actor || '系统' }}</span>
          </li>
        </ul>
      </section>
    </template>

    <!-- 模拟推送弹窗 -->
    <div v-if="pushOpen && detail" class="ac-modal-mask" @click.self="pushOpen = false">
      <div class="ac-modal" role="dialog" aria-label="模拟推送">
        <div class="ac-modal-head">
          <h3>模拟推送（不实际发送短信/邮件）</h3>
          <button type="button" class="ac-btn ac-btn--ghost" aria-label="关闭" @click="pushOpen = false">×</button>
        </div>
        <p class="ac-modal-note">预警事件与推送记录分开保存：模拟推送失败不影响事件本身。</p>
        <div class="ac-modal-sec">
          <p>渠道（多选）</p>
          <label v-for="c in pushChannelOptions" :key="c.value" class="ac-check">
            <input v-model="pushChannels" type="checkbox" :value="c.value" /> {{ c.label }}
          </label>
        </div>
        <div class="ac-modal-sec">
          <p>接收组（模拟收件人，已脱敏）</p>
          <label v-for="g in pushGroupOptions" :key="g.value" class="ac-check ac-check--col">
            <span class="ac-check-row">
              <input v-model="pushGroups" type="checkbox" :value="g.value" /> {{ g.label }}
            </span>
            <small class="ac-check-sub">{{ g.recipients_masked.join('、') }} · {{ g.source === 'config' ? '真实配置' : '模拟收件人' }}</small>
          </label>
        </div>
        <div class="ac-modal-sec">
          <p>消息内容（可修改）</p>
          <textarea v-model="pushBody" class="ac-textarea" rows="5" aria-label="推送消息内容"></textarea>
        </div>
        <div v-if="pushResult.length" class="ac-modal-sec">
          <p>模拟回执</p>
          <ul class="ac-push-results">
            <li v-for="r in pushResult" :key="r.receipt_no" :class="`ac-push-result--${r.status}`">
              {{ channelName(r.channel) }} · {{ pushStatusText(r.status) }} · 回执号 {{ r.receipt_no }}
              <small>{{ r.reason }}</small>
            </li>
          </ul>
        </div>
        <div v-if="opError" class="ac-note ac-note--warn" role="alert">{{ opError }}</div>
        <div class="ac-modal-foot">
          <button type="button" class="ac-btn" @click="pushOpen = false">关闭</button>
          <button type="button" class="ac-btn ac-btn--primary" :disabled="pushing || !pushChannels.length || !pushGroups.length" @click="sendPush">
            {{ pushing ? '发送中…' : '执行模拟发送' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 动作确认弹窗（指派 / 撤销 / 重开） -->
    <div v-if="pendingAction" class="ac-modal-mask" @click.self="pendingAction = null">
      <div class="ac-modal ac-modal--sm" role="dialog" :aria-label="pendingAction.label">
        <div class="ac-modal-head">
          <h3>{{ pendingAction.label }}</h3>
          <button type="button" class="ac-btn ac-btn--ghost" aria-label="关闭" @click="pendingAction = null">×</button>
        </div>
        <div v-if="pendingAction.action === 'assign'" class="ac-modal-sec">
          <p>指派给</p>
          <select v-model="actionAssignee" class="ac-select" aria-label="选择负责人">
            <option value="">请选择…</option>
            <option v-for="g in pushGroupOptions" :key="g.value" :value="g.label">{{ g.label }}</option>
          </select>
        </div>
        <div v-if="pendingAction.needReason" class="ac-modal-sec">
          <p>{{ pendingAction.action === 'revoke' ? '撤销原因（必填）' : '重新打开原因' }}</p>
          <textarea v-model="actionReason" class="ac-textarea" rows="3" aria-label="原因"></textarea>
        </div>
        <div v-if="actionError" class="ac-note ac-note--warn">{{ actionError }}</div>
        <div class="ac-modal-foot">
          <button type="button" class="ac-btn" @click="pendingAction = null">取消</button>
          <button type="button" class="ac-btn ac-btn--primary" :disabled="acting" @click="doAction">{{ acting ? '执行中…' : '确认' }}</button>
        </div>
      </div>
    </div>

    <!-- 规则配置弹窗 -->
    <div v-if="rulesOpen" class="ac-modal-mask" @click.self="rulesOpen = false">
      <div class="ac-modal" role="dialog" aria-label="规则配置">
        <div class="ac-modal-head">
          <h3>规则配置</h3>
          <button type="button" class="ac-btn ac-btn--ghost" aria-label="关闭" @click="rulesOpen = false">×</button>
        </div>
        <div class="ac-modal-sec">
          <p>实时观测规则（{{ rules.realtime?.name }}）</p>
          <p class="ac-rule-line">
            叶绿素a ≥ {{ rules.realtime?.thresholds?.moderate }} → 红色告警；≥ {{ rules.realtime?.thresholds?.light }} → 黄色预警（μg/L）
          </p>
          <p class="ac-rule-note">{{ rules.realtime?.note }}</p>
        </div>
        <div class="ac-modal-sec">
          <p>预测预警规则（{{ rules.predicted?.enabled ? '已启用' : '预留未启用' }}）</p>
          <div class="ac-rule-grid">
            <label>超阈概率门槛 <input v-model.number="rulesDraft.predicted.probability_threshold" type="number" min="0.01" max="0.99" step="0.01" /></label>
            <label>最短预测期（天）<input v-model.number="rulesDraft.predicted.min_horizon_days" type="number" min="1" max="365" /></label>
            <label>最长预测期（天）<input v-model.number="rulesDraft.predicted.max_horizon_days" type="number" min="1" max="365" /></label>
          </div>
          <p class="ac-rule-note">{{ rules.predicted?.note }}</p>
        </div>
        <div class="ac-modal-sec">
          <p>通知策略（哪些变化产生未读通知）</p>
          <label v-for="(label, key) in notifyOptions" :key="key" class="ac-check">
            <input v-model="rulesDraft.notify[key]" type="checkbox" /> {{ label }}
          </label>
        </div>
        <div class="ac-modal-sec">
          <p>自动模拟推送（新触发时自动生成模拟推送记录）</p>
          <label class="ac-check">
            <input v-model="rulesDraft.auto_simulate_push.enabled" type="checkbox" /> 新事件触发时自动模拟推送
          </label>
          <p class="ac-rule-note">默认关闭：仅人工推送，避免持续刷屏；开启后新触发/升级会自动生成模拟回执。</p>
        </div>
        <div class="ac-modal-foot">
          <button type="button" class="ac-btn" @click="rulesOpen = false">取消</button>
          <button type="button" class="ac-btn ac-btn--primary" :disabled="savingRules" @click="saveRules">{{ savingRules ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 预案库弹窗 -->
    <div v-if="plansOpen" class="ac-modal-mask" @click.self="plansOpen = false">
      <div class="ac-modal" role="dialog" aria-label="预案库">
        <div class="ac-modal-head">
          <h3>预案库</h3>
          <button type="button" class="ac-btn ac-btn--ghost" aria-label="关闭" @click="plansOpen = false">×</button>
        </div>
        <p v-if="!plans.length" class="ac-empty">预案库为空。</p>
        <details v-for="p in plans" :key="p.id" class="ac-plan-item">
          <summary>
            <strong>{{ p.name }}</strong>
            <span class="ac-chip ac-chip--type">{{ p.stage === 'predicted' ? '预测准备' : '实时处置' }}</span>
            <small>{{ p.scope }} · 版本 {{ p.version }} · {{ p.department }}</small>
          </summary>
          <ul class="ac-plan-measures ac-plan-measures--static">
            <li v-for="m in p.measures" :key="m.text"><span>{{ m.text }}</span><small>{{ groupName(m.group) }} · {{ m.due }}</small></li>
          </ul>
        </details>
        <p class="ac-rule-note">预案措施为通用监测/巡查/研判动作；正式预案文本以项目文档为准。</p>
      </div>
    </div>
  </main>
</template>

<script setup>
// 预警与应急预案中心（三栏）：实时/预测事件同列表分标签，共用处理流程；
// 详情按类型区分内容；右侧为规则匹配的应急预案（可解释匹配依据）；
// 短信/邮件为模拟推送（明确标注，绝不伪装真实发送）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DataModeBadge from '../components/common/DataModeBadge.vue'
import { fetchStationObservations, fmtMeasure, OBS_HISTORY_START, REALTIME_VARIABLES, todayLocalDate } from '../services/realtime.js'
import {
  EVIDENCE_STATE_TEXT,
  EVENT_STATUS_TEXT,
  EVENT_TYPE_TEXT,
  FLOW_STEPS,
  PUSH_GROUP_TEXT,
  PUSH_STATUS_TEXT,
  RECORD_ACTION_TEXT,
  STATUS_ACTIONS,
  fetchCenterEvent,
  fetchCenterNotifications,
  fetchCenterOverview,
  fetchCenterRecords,
  postCenterAction,
  postCenterAdoptPlan,
  postCenterPush,
  postCenterRules,
  postCenterTaskUpdate
} from '../services/alertCenter.js'
import { ALERT_LEVEL_TEXT, evaluateAlerts, formatAlertTime } from '../services/alerts.js'

const state = ref('loading')
const overview = ref(null)
const detail = ref(null)
const selectedId = ref('')
const typeTab = ref('all')
const statusFilter = ref('all')
const search = ref('')
const detailTab = ref('info')
const evaluating = ref(false)

const records = ref(null)
const recordTab = ref('records')
const recordsExpanded = ref(false)

const pushOpen = ref(false)
const pushChannels = ref(['sms'])
const pushGroups = ref(['monitor'])
const pushBody = ref('')
const pushing = ref(false)
const pushResult = ref([])

const pendingAction = ref(null)
const actionAssignee = ref('')
const actionReason = ref('')
const actionError = ref('')
const acting = ref(false)
const adopting = ref(false)
const savingRules = ref(false)
// 写操作（确认/指派/推送/预案/规则）失败提示：不静默吞错
const opError = ref('')

const rulesOpen = ref(false)
const plansOpen = ref(false)
const rulesDraft = ref(null)

const trendState = ref('idle')
const trendRows = ref([])
const timelineExpanded = ref(false)
const latestState = ref('idle')
const latestRows = ref([])

let timer = null
const route = useRoute()

const typeTabs = [
  { value: 'all', label: '全部' },
  { value: 'realtime', label: '实时' },
  { value: 'predicted', label: '预测' }
]
const recordTabs = [
  { value: 'records', label: '处理记录' },
  { value: 'pushes', label: '模拟推送记录' },
  { value: 'audit', label: '操作日志' }
]
const pushChannelOptions = [
  { value: 'sms', label: '短信' },
  { value: 'email', label: '邮件' }
]
const pushGroupOptions = computed(() => {
  const view = overview.value?.push_groups
  if (Array.isArray(view) && view.length) return view.map((g) => ({ ...g, label: g.label }))
  return Object.entries(PUSH_GROUP_TEXT).map(([value, label]) => ({ value, label, recipients_masked: [], source: 'simulated' }))
})
const notifyOptions = {
  new_event: '新预警触发',
  escalation: '风险升级',
  recovery: '指标恢复（待复核）',
  unverified: '数据待核实',
  process: '处理动态（指派等）',
  push_failure: '模拟推送失败'
}

const stats = computed(() => overview.value?.stats || {})
const rules = computed(() => overview.value?.rules || {})
const plans = computed(() => overview.value?.plans || [])
const events = computed(() => overview.value?.events || [])
const availableActions = computed(() => (detail.value ? STATUS_ACTIONS[detail.value.status] || [] : []))
const canAdoptPlan = computed(() => detail.value && ['acknowledged', 'processing'].includes(detail.value.status))
const doneTasks = computed(() => (detail.value?.plan ? detail.value.plan.tasks.filter((t) => t.status === 'done').length : 0))

const recordRows = computed(() => {
  if (!records.value) return []
  if (recordTab.value === 'pushes') return records.value.pushes || []
  if (recordTab.value === 'audit') return records.value.audit || []
  return records.value.records || []
})
const visibleRecords = computed(() => (recordsExpanded.value ? recordRows.value : recordRows.value.slice(0, 6)))

const trendPoints = computed(() => {
  const series = trendRows.value
    .filter((r) => r.variable_code === 'chlorophyll_a' && r.observation_status === 'ok' && r.value != null)
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
  const values = series.map((r) => Number(r.value))
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 26)
  const span = max - min || 1
  return series.map((r, i) => ({
    t: formatAlertTime(r.observed_at).slice(5),
    x: series.length === 1 ? 300 : 10 + (i / (series.length - 1)) * 580,
    y: 190 - ((Number(r.value) - min) / span) * 170
  }))
})
const trendPolyline = computed(() => trendPoints.value.map((p) => `${p.x},${p.y}`).join(' '))
const triggerX = computed(() => {
  const triggerAt = detail.value?.evidence?.triggered_at
  if (!triggerAt || trendPoints.value.length < 2) return null
  const target = String(triggerAt).slice(0, 16)
  const idx = trendRows.value.findIndex((r) => String(r.observed_at || '').slice(0, 16) === target)
  if (idx < 0) return null
  const p = trendPoints.value[Math.min(idx, trendPoints.value.length - 1)]
  return p ? p.x : null
})

function yFor(value) {
  const rows = trendRows.value
    .filter((r) => r.variable_code === 'chlorophyll_a' && r.observation_status === 'ok' && r.value != null)
  if (!rows.length) return 190
  const values = rows.map((r) => Number(r.value))
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 26)
  return 190 - ((value - min) / (max - min || 1)) * 170
}

function flowState(step) {
  if (!detail.value) return ''
  const order = FLOW_STEPS
  if (detail.value.status === 'revoked') return step === 'pending' ? 'done' : ''
  const at = order.indexOf(detail.value.status)
  const idx = order.indexOf(step)
  if (at < 0) return ''
  if (idx < at) return 'done'
  if (idx === at) return 'now'
  return ''
}

function levelText(level) {
  return ALERT_LEVEL_TEXT[level] || level
}
function groupName(group) {
  return PUSH_GROUP_TEXT[group] || group || '—'
}
function channelName(channel) {
  return channel === 'email' ? '邮件' : channel === 'sms' ? '短信' : channel
}
function pushStatusText(status) {
  return PUSH_STATUS_TEXT[status] || status
}
function fmtTime(iso) {
  return formatAlertTime(iso)
}
function fmtClock(iso) {
  return formatAlertTime(iso).slice(5) || '—'
}
function recordMain(r) {
  const prefix = r.event_no ? `${r.event_no} · ` : ''
  if (recordTab.value === 'pushes') {
    return `${prefix}${channelName(r.channel)} 模拟${r.status === 'simulated_success' ? '成功' : '失败'} → ${(r.groups || []).join('、')}${r.reason ? `（${r.reason}）` : ''}`
  }
  if (recordTab.value === 'audit') return `${prefix}${r.action || ''} ${r.detail || ''} ${r.target || ''}`
  return `${prefix}${RECORD_ACTION_TEXT[r.action] || r.action} · ${r.detail || ''}`
}

function openPushDialog() {
  const ev = detail.value?.evidence || {}
  pushBody.value = `【太湖水华预警·模拟】${detail.value.station_name} 叶绿素a达到${levelText(detail.value.level)}阈值，观测值 ${ev.value != null ? ev.value : '缺测'} ${ev.unit || ''}，观测时间 ${fmtTime(ev.observed_at)}。请核实并查看关联预案。编号 ${detail.value.no}。（模拟消息，不实际发送）`
  pushResult.value = []
  pushOpen.value = true
}

async function sendPush() {
  pushing.value = true
  opError.value = ''
  try {
    const { results } = await postCenterPush(selectedId.value, {
      channels: pushChannels.value,
      groups: pushGroups.value,
      body: pushBody.value
    })
    pushResult.value = results
    await refreshDetail()
    await loadRecords(true)
  } catch (err) {
    opError.value = err?.message || '模拟推送失败'
  } finally {
    pushing.value = false
  }
}

function openAction(a) {
  actionError.value = ''
  opError.value = ''
  actionAssignee.value = detail.value?.assignee || ''
  actionReason.value = ''
  pendingAction.value = a
  if (!a.needReason && a.action !== 'assign') {
    doAction()
  }
}

async function doAction() {
  const a = pendingAction.value
  if (!a) return
  if (a.action === 'assign' && !actionAssignee.value) {
    actionError.value = '请选择负责人'
    return
  }
  if (a.needReason && !actionReason.value.trim()) {
    actionError.value = '请填写原因'
    return
  }
  acting.value = true
  try {
    await postCenterAction(selectedId.value, a.action, {
      assignee: actionAssignee.value || undefined,
      reason: actionReason.value || undefined,
      comment: actionReason.value || undefined
    })
    pendingAction.value = null
    await refreshDetail()
    await Promise.all([load(true), loadRecords(true)])
  } catch (err) {
    actionError.value = err?.message || '操作失败'
  } finally {
    acting.value = false
  }
}

async function adoptPlan(planId) {
  adopting.value = true
  opError.value = ''
  try {
    detail.value = await postCenterAdoptPlan(selectedId.value, planId)
    detail.value.matched_plan = detail.value.matched_plan || null
    await Promise.all([load(true), loadRecords(true)])
  } catch (err) {
    opError.value = err?.message || '预案采用失败'
  } finally {
    adopting.value = false
  }
}

async function updateTask(task, status) {
  opError.value = ''
  try {
    await postCenterTaskUpdate(selectedId.value, task.id, { status })
    await refreshDetail()
    await loadRecords(true)
  } catch (err) {
    opError.value = err?.message || '任务状态更新失败'
  }
}

function openRules() {
  rulesDraft.value = {
    predicted: {
      probability_threshold: rules.value.predicted?.probability_threshold ?? 0.6,
      min_horizon_days: rules.value.predicted?.min_horizon_days ?? 1,
      max_horizon_days: rules.value.predicted?.max_horizon_days ?? 90
    },
    notify: { ...(rules.value.notify || {}) },
    auto_simulate_push: { ...(rules.value.auto_simulate_push || {}) }
  }
  rulesOpen.value = true
}

async function saveRules() {
  savingRules.value = true
  opError.value = ''
  try {
    await postCenterRules({
      notify: rulesDraft.value.notify,
      auto_simulate_push: rulesDraft.value.auto_simulate_push,
      predicted: rulesDraft.value.predicted
    })
    rulesOpen.value = false
    await load(true)
  } catch (err) {
    opError.value = err?.message || '规则保存失败'
  } finally {
    savingRules.value = false
  }
}

async function load(force = false) {
  if (force && !overview.value) state.value = 'loading'
  try {
    const [data, notifications] = await Promise.all([
      fetchCenterOverview({ force, type: typeTab.value, status: statusFilter.value, search: search.value }),
      fetchCenterNotifications({ force })
    ])
    overview.value = data
    if (notifications.unread_count !== undefined) overview.value.unread_count = notifications.unread_count
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

async function loadRecords(force = false) {
  try {
    records.value = await fetchCenterRecords({ force })
  } catch {
    records.value = null
  }
}

async function refreshDetail() {
  if (!selectedId.value) return
  try {
    detail.value = await fetchCenterEvent(selectedId.value, { force: true })
  } catch {
    detail.value = null
  }
}

async function loadTrend() {
  if (!detail.value || detail.value.type !== 'realtime' || !detail.value.station_id) {
    trendRows.value = []
    return
  }
  trendState.value = 'loading'
  try {
    trendRows.value = await fetchStationObservations(detail.value.station_id, {
      window: 'range',
      start: OBS_HISTORY_START,
      end: todayLocalDate()
    })
    trendState.value = 'ok'
  } catch {
    trendState.value = 'error'
  }
}

async function loadLatest() {
  if (!detail.value || detail.value.type !== 'realtime' || !detail.value.station_id) {
    latestRows.value = []
    return
  }
  latestState.value = 'loading'
  try {
    latestRows.value = await fetchStationObservations(detail.value.station_id, { window: 'latest' })
    latestState.value = 'ok'
  } catch {
    latestState.value = 'error'
  }
}

const detailTimeline = computed(() => {
  const rows = [...(detail.value?.records || [])].reverse()
  return timelineExpanded.value ? rows : rows.slice(0, 4)
})

const latestObs = computed(() => {
  if (!latestRows.value.length) return []
  return REALTIME_VARIABLES.map(({ code, label, unit }) => {
    const row = latestRows.value.find((r) => r.variable_code === code)
    const status = row ? row.observation_status : 'missing'
    return {
      code,
      label,
      unit,
      value: row && row.value != null && status !== 'missing' ? fmtMeasure(row.value) : '--',
      flag: status === 'ok' ? '正常' : status === 'qc_rejected' ? '质控不合格' : '缺测',
      tone: status === 'ok' ? 'ok' : status === 'qc_rejected' ? 'bad' : 'na'
    }
  })
})

const latestObservedAt = computed(() => {
  const times = latestRows.value.map((r) => r.observed_at).filter(Boolean).sort()
  return times.length ? times[times.length - 1] : null
})

function selectEvent(id) {
  selectedId.value = id
}

async function runEvaluate() {
  evaluating.value = true
  opError.value = ''
  try {
    await evaluateAlerts()
    await load(true)
    await refreshDetail()
    await loadRecords(true)
  } catch (err) {
    opError.value = err?.message || '巡检失败'
  } finally {
    evaluating.value = false
  }
}

watch(selectedId, async (id) => {
  detailTab.value = 'info'
  timelineExpanded.value = false
  latestRows.value = []
  if (!id) {
    detail.value = null
    return
  }
  await refreshDetail()
  loadLatest()
  await loadTrend()
})
watch(detailTab, (tab) => {
  if (tab === 'trend' && detail.value?.type === 'realtime' && !trendRows.value.length) loadTrend()
})
watch([typeTab, statusFilter], () => load(true))
let searchTimer = null
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 300)
})
watch(pushOpen, (open) => {
  if (open) openPushDialog()
})
watch(rulesOpen, (open) => {
  if (open) openRules()
})
// 铃铛通知跳转：/alerts?event=xxx（页面已挂载时 query 变化也要选中对应事件）
watch(() => route.query.event, () => {
  selectFromQuery()
})

async function selectFromQuery() {
  const fromQuery = typeof route.query.event === 'string' ? route.query.event : ''
  if (!fromQuery) return false
  if (events.value.some((e) => e.id === fromQuery)) {
    selectEvent(fromQuery)
    return true
  }
  // 事件不在当前筛选视图：清空筛选后重取
  typeTab.value = 'all'
  statusFilter.value = 'all'
  search.value = ''
  await load(true)
  if (events.value.some((e) => e.id === fromQuery)) {
    selectEvent(fromQuery)
    return true
  }
  return false
}

onMounted(async () => {
  await load(true)
  await loadRecords()
  await selectFromQuery()
  if (!selectedId.value && events.value.length) selectEvent(events.value[0].id)
  timer = setInterval(() => {
    load(true)
    loadRecords(true)
  }, 60_000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  clearTimeout(searchTimer)
})
</script>

<style scoped>
.page-ac {
  max-width: 1440px;
  margin: 0 auto;
  padding: 14px 20px 32px;
  display: grid;
  gap: 12px;
}
.ac-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.ac-kicker { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.22em; color: var(--color-primary); margin: 0; }
.ac-title h1 { margin: 2px 0 0; font-family: var(--font-display); font-size: clamp(20px, 2vw, 26px); color: var(--text-primary); }
.ac-head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.ac-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 32px;
  padding: 2px 14px;
  font-size: 12.5px;
  cursor: pointer;
}
.ac-btn:disabled { opacity: 0.55; cursor: default; }
.ac-btn--primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
  font-weight: 650;
}
.ac-btn--ghost { border-color: var(--border-subtle); background: var(--surface-panel-soft); }
.ac-btn--wide { width: 100%; min-height: 38px; }

.ac-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.ac-stat {
  display: grid;
  gap: 1px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel, 14px);
  background: var(--surface-panel);
  padding: 12px 16px;
}
.ac-stat strong { font-family: var(--font-mono); font-size: 24px; color: var(--text-primary); }
.ac-stat small { font-size: 12px; color: var(--text-secondary); margin-left: 3px; font-family: var(--font-mono); }
.ac-stat span { font-size: 12.5px; color: var(--text-secondary); }
.ac-stat-sub { font-size: 10.5px; color: var(--text-muted); }

.ac-error, .ac-loading {
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
  padding: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 12px;
}

.ac-grid {
  display: grid;
  grid-template-columns: minmax(280px, 26%) minmax(0, 1fr) minmax(260px, 29%);
  gap: 10px;
  align-items: start;
}
.ac-col {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel, 14px);
  background: var(--surface-panel);
  padding: 12px;
  display: grid;
  gap: 10px;
  align-content: start;
}
.ac-list, .ac-plan { max-height: 640px; overflow-y: auto; }

.ac-tabs { display: inline-flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.ac-tab {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  border-radius: 999px;
  font-size: 12px;
  padding: 4px 13px;
  cursor: pointer;
}
.ac-tab--on { color: var(--text-primary); border-color: var(--color-primary); background: color-mix(in srgb, var(--color-primary) 12%, transparent); }

.ac-list-tools { display: flex; gap: 6px; }
.ac-select, .ac-input {
  min-height: 30px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  padding: 2px 8px;
}
.ac-input { flex: 1; min-width: 0; }
.ac-select--sm { min-height: 26px; font-size: 11px; }

.ac-empty { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--text-muted); border: 1px dashed var(--border-subtle); border-radius: 12px; padding: 14px; }

.ac-events { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.ac-event {
  width: 100%;
  display: grid;
  gap: 4px;
  text-align: left;
  border: 1px solid var(--border-subtle);
  border-left-width: 3px;
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
  cursor: pointer;
  color: var(--text-primary);
}
.ac-event--light { border-left-color: var(--risk-medium, #f5b45d); }
.ac-event--moderate { border-left-color: var(--risk-critical, #ef4444); }
.ac-event--on { border-color: var(--color-primary); background: color-mix(in srgb, var(--color-primary) 8%, var(--surface-panel)); }
.ac-event-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.ac-event-name { font-size: 13px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ac-event-title { font-size: 11px; color: var(--text-secondary); }
.ac-event-meta { justify-content: space-between; font-size: 10.5px; color: var(--text-muted); font-family: var(--font-mono); }
.ac-event-status { font-size: 10px; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border-subtle); color: var(--text-secondary); flex: none; }
.ac-event-status--pending { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 45%, transparent); }
.ac-event-status--processing { color: var(--color-primary); border-color: color-mix(in srgb, var(--color-primary) 45%, transparent); }
.ac-event-status--review { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 50%, transparent); }
.ac-event-status--closed, .ac-event-status--revoked { color: var(--text-muted); }

.ac-chip {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  flex: none;
}
.ac-chip--type { color: var(--text-secondary); background: var(--surface-panel-soft); }
.ac-chip--light { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 55%, transparent); }
.ac-chip--moderate { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 60%, transparent); }
.ac-chip--st-pending { color: var(--risk-critical, #ef4444); }
.ac-chip--st-processing { color: var(--color-primary); }
.ac-chip--st-review { color: var(--risk-medium, #f5b45d); }
.ac-chip--st-closed, .ac-chip--st-revoked { color: var(--text-muted); }
.ac-chip--mono { font-family: var(--font-mono); }
.ac-chip--ok { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.ac-chip--ev-valid { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 45%, transparent); }
.ac-chip--ev-recovered { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.ac-chip--ev-unverified { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 50%, transparent); }

.ac-detail-head { display: grid; gap: 6px; }
.ac-detail-head h2 { margin: 0; font-size: 16px; color: var(--text-primary); }
.ac-detail-chips { display: flex; flex-wrap: wrap; gap: 6px; }

.ac-note { font-size: 12px; line-height: 1.7; border-radius: 10px; padding: 8px 12px; border: 1px solid var(--border-subtle); }
.ac-note--warn { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 50%, transparent); background: color-mix(in srgb, var(--risk-medium) 8%, transparent); }
.ac-note--ok { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); background: color-mix(in srgb, var(--risk-low) 8%, transparent); }

.ac-facts {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}
.ac-facts > div {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
}
.ac-facts dt { font-size: 10.5px; color: var(--text-muted); }
.ac-facts dd { margin: 0; font-size: 12.5px; color: var(--text-secondary); }
.ac-facts dd b { font-family: var(--font-mono); font-size: 15px; color: var(--text-primary); }

.ac-flow { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.ac-flow-step { display: grid; justify-items: center; gap: 2px; }
.ac-flow-step i {
  font-style: normal;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}
.ac-flow-step em { font-style: normal; font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.ac-flow-step.done i { background: color-mix(in srgb, var(--color-primary) 18%, transparent); border-color: color-mix(in srgb, var(--color-primary) 55%, transparent); color: var(--text-primary); }
.ac-flow-step.now i { background: var(--color-primary); border-color: var(--color-primary); color: #fff; font-weight: 700; }
.ac-flow-step.now em { color: var(--text-primary); font-weight: 650; }
.ac-flow-line { flex: 1; min-width: 14px; height: 2px; background: var(--border-subtle); border-radius: 2px; }
.ac-flow-line--done { background: color-mix(in srgb, var(--color-primary) 55%, transparent); }

.ac-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ac-link { font-size: 12.5px; color: var(--color-primary); text-decoration: none; }
.ac-link:hover { text-decoration: underline; }
.ac-assignee { margin: 0; font-size: 11.5px; color: var(--text-muted); }

.ac-plan-run { display: grid; gap: 8px; border-top: 1px dashed var(--border-subtle); padding-top: 10px; }

/* 详情栏内小节：最新观测 / 处理动态 */
.ac-sec { display: grid; gap: 7px; border-top: 1px dashed var(--border-subtle); padding-top: 10px; }
.ac-sec h4 { margin: 0; font-size: 12.5px; color: var(--text-primary); display: flex; align-items: baseline; gap: 8px; }
.ac-sec-tag { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); font-weight: 400; }
.ac-sec-empty { margin: 0; font-size: 11.5px; color: var(--text-muted); }
.ac-latest-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 6px; }
.ac-latest-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  padding: 5px 9px;
}
.ac-latest-k { font-size: 11px; color: var(--text-secondary); flex: 1; min-width: 0; }
.ac-latest-v { flex: none; max-width: 60%; text-align: right; }
.ac-latest-v b { font-family: var(--font-mono); font-size: 12px; color: var(--text-primary); overflow-wrap: anywhere; }
.ac-latest-v small { font-size: 9.5px; color: var(--text-muted); }
.ac-flag { font-size: 9.5px; padding: 1px 6px; border-radius: 999px; border: 1px solid var(--border-subtle); flex: none; }
.ac-flag--ok { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.ac-flag--bad { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 50%, transparent); }
.ac-flag--na { color: var(--text-muted); }

.ac-timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.ac-tl-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 5px 0;
  border-bottom: 1px dashed var(--border-subtle);
  font-size: 11.5px;
}
.ac-tl-row:last-child { border-bottom: none; }
.ac-tl-time { flex: none; color: var(--text-muted); font-size: 10px; }
.ac-tl-main { flex: 1; min-width: 0; color: var(--text-secondary); }
.ac-tl-main b { color: var(--text-primary); font-weight: 600; }
.ac-tl-actor { flex: none; color: var(--text-muted); font-size: 10px; }
.ac-tl-more {
  justify-self: start;
  appearance: none;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 0;
}

.ac-check--col { display: grid; gap: 2px; margin-right: 10px; }
.ac-check-row { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-primary); }
.ac-check-sub { font-size: 10px; color: var(--text-muted); }
.ac-plan-run h3 { margin: 0; font-size: 13.5px; color: var(--text-primary); }
.ac-plan-meta { margin: 0; font-size: 11px; color: var(--text-muted); }
.ac-tasks { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.ac-task {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 7px 10px;
}
.ac-task-main { display: grid; gap: 1px; min-width: 0; }
.ac-task-main strong { font-size: 12.5px; color: var(--text-primary); font-weight: 600; }
.ac-task-main small { font-size: 10.5px; color: var(--text-muted); }

.ac-trend { display: grid; gap: 6px; }
.ac-trend svg { width: 100%; height: 200px; display: block; }
.ac-grid { stroke: var(--border-subtle); stroke-width: 1; stroke-dasharray: 4 4; }
.ac-grid--moderate { stroke: color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent); }
.ac-grid-label { font-size: 9px; fill: var(--risk-medium, #f5b45d); }
.ac-grid-label--moderate { fill: var(--risk-critical, #ef4444); }
.ac-trigger-line { stroke: var(--color-primary); stroke-width: 1.4; stroke-dasharray: 3 3; }
.ac-trend-line { fill: none; stroke: var(--color-primary); stroke-width: 2; }
.ac-trend-dot { fill: var(--color-primary); }
.ac-trend-axis { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }

.ac-plan-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ac-plan-head h3, .ac-plan-run h3 { margin: 0; font-size: 13.5px; color: var(--text-primary); }
.ac-plan-name { margin: 0; font-size: 14px; font-weight: 700; color: var(--text-primary); }
.ac-plan-reasons { display: grid; gap: 4px; }
.ac-plan-reasons p { margin: 0; font-size: 11px; color: var(--text-muted); }
.ac-plan-reasons ul { margin: 0; padding-left: 16px; display: grid; gap: 2px; }
.ac-plan-reasons li { font-size: 11.5px; color: var(--text-secondary); }
.ac-plan-measures-title { margin: 4px 0 0; font-size: 11px; color: var(--text-muted); }
.ac-plan-measures { list-style: none; margin: 0; padding: 0; display: grid; gap: 5px; }
.ac-plan-measures li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-primary);
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  padding: 5px 8px;
}
.ac-plan-measures li small { color: var(--text-muted); flex: none; }
.ac-plan-measures--static li { border-style: solid; }
.ac-plan-note { margin: 0; font-size: 10px; color: var(--text-muted); }

.ac-records { border: 1px solid var(--border-subtle); border-radius: var(--radius-panel, 14px); background: var(--surface-panel); padding: 12px; display: grid; gap: 8px; }
.ac-records .ac-tabs { align-items: center; }
.ac-records-expand { margin-left: auto; appearance: none; border: none; background: none; color: var(--color-primary); font-size: 11.5px; cursor: pointer; }
.ac-record-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.ac-record {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-size: 11.5px;
  color: var(--text-secondary);
  border-bottom: 1px dashed var(--border-subtle);
  padding: 4px 2px;
}
.ac-record:last-child { border-bottom: none; }
.ac-record-time { flex: none; color: var(--text-muted); font-size: 10.5px; }
.ac-record-main { flex: 1; min-width: 0; }
.ac-record-actor { flex: none; color: var(--text-muted); font-size: 10.5px; }

.ac-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1400;
  background: rgba(4, 12, 24, 0.45);
  display: grid;
  place-items: center;
  padding: 20px;
}
.ac-modal {
  width: min(520px, 100%);
  max-height: min(80vh, 720px);
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  background: var(--panel-strong, var(--surface-panel));
  box-shadow: 0 24px 64px rgba(2, 8, 18, 0.35);
  padding: 16px;
  display: grid;
  gap: 12px;
}
.ac-modal--sm { width: min(420px, 100%); }
.ac-modal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ac-modal-head h3 { margin: 0; font-size: 15px; color: var(--text-primary); }
.ac-modal-note { margin: 0; font-size: 11.5px; color: var(--risk-medium, #f5b45d); }
.ac-modal-sec { display: grid; gap: 6px; }
.ac-modal-sec > p { margin: 0; font-size: 11.5px; color: var(--text-muted); }
.ac-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-primary); margin-right: 12px; }
.ac-textarea {
  width: 100%;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 10px;
  resize: vertical;
}
.ac-modal-foot { display: flex; justify-content: flex-end; gap: 8px; }
.ac-push-results { list-style: none; margin: 0; padding: 0; display: grid; gap: 5px; }
.ac-push-results li { display: grid; gap: 1px; font-size: 12px; border-radius: 8px; border: 1px solid var(--border-subtle); padding: 6px 9px; }
.ac-push-results li small { font-size: 10.5px; color: var(--text-muted); }
.ac-push-result--simulated_success { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.ac-push-result--simulated_failed { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 50%, transparent); }
.ac-rule-line { margin: 0; font-size: 12.5px; color: var(--text-primary); font-family: var(--font-mono); }
.ac-rule-note { margin: 0; font-size: 10.5px; line-height: 1.7; color: var(--text-muted); }
.ac-rule-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.ac-rule-grid label { display: grid; gap: 3px; font-size: 11px; color: var(--text-secondary); }
.ac-rule-grid input {
  min-height: 28px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  padding: 2px 8px;
}
.ac-plan-item { border: 1px solid var(--border-subtle); border-radius: 10px; padding: 8px 10px; }
.ac-plan-item summary { display: flex; align-items: center; gap: 8px; cursor: pointer; flex-wrap: wrap; }
.ac-plan-item summary strong { font-size: 13px; color: var(--text-primary); }
.ac-plan-item summary small { color: var(--text-muted); font-size: 10.5px; }

@media (max-width: 1100px) {
  .ac-grid { grid-template-columns: 1fr; }
  .ac-list, .ac-plan { max-height: none; }
}
</style>
