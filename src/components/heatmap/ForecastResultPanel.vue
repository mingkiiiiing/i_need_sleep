<template>
  <div class="frp">
    <div class="frp-tabs" role="tablist" aria-label="预测结果视图切换">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        role="tab"
        class="frp-tab"
        :class="{ active: activeTab === tab.key }"
        :aria-selected="String(activeTab === tab.key)"
        :data-role="`result-tab-${tab.key}`"
        @click="activeTab = tab.key"
      >{{ tab.label }}</button>
    </div>

    <!-- 站点环比变化：前后值同图对照，地图同步标出全部站点 -->
    <div v-if="diffEnabled" class="frp-diff" data-role="panel-diff-summary" aria-label="站点环比变化">
      <div class="frp-diff-head">
        <b>站点变化</b>
        <span>对比 {{ diffBaseTime }}</span>
      </div>
      <div class="frp-diff-counts" data-role="panel-diff-counts">
        <span class="frp-diff-stat frp-diff-stat--up"><b>{{ diffSummary.up }}</b>上升</span>
        <span class="frp-diff-stat frp-diff-stat--down"><b>{{ diffSummary.down }}</b>下降</span>
        <span class="frp-diff-stat"><b>{{ diffSummary.flat }}</b>持平/缺测</span>
      </div>
      <div v-if="diffVisualRows.length" class="frp-diff-chart" data-role="panel-diff-top">
        <div v-for="r in diffVisualRows" :key="r.id" class="frp-diff-row" :data-status="r.status">
          <span class="frp-diff-name">{{ r.name }}</span>
          <span class="frp-diff-track">
            <i class="frp-diff-link" :style="r.linkStyle"></i>
            <i class="frp-diff-before" :style="{ left: `${r.beforePct}%` }" title="上一快照"></i>
            <i class="frp-diff-after" :style="{ left: `${r.afterPct}%` }" title="当前快照"></i>
          </span>
          <b class="frp-diff-delta">{{ r.deltaText }}</b>
        </div>
      </div>
      <p v-else class="frp-note">暂无可对比站点。</p>
    </div>

    <!-- ===== 结果总览 ===== -->
    <div v-if="activeTab === 'overview'" class="frp-body" role="tabpanel" aria-label="结果总览" data-role="result-overview">
      <div class="frp-object">
        <span class="frp-object-name">{{ scope === 'station' ? stationName : '全湖' }}</span>
        <span class="frp-object-tag">{{ stop ? stop.title : '—' }}</span>
        <button
          v-if="scope === 'station'"
          type="button"
          class="frp-back"
          data-role="back-to-lake"
          @click="$emit('back-to-lake')"
        >返回全湖结果</button>
      </div>

      <StatePanel
        v-if="modelState === 'loading'"
        state="loading"
        title="正在加载预测结果…"
        description="读取后台按最新实测快照预生成的预测结果；仅当实测数据或模型版本变化时才会重新推理。"
      />
      <StatePanel
        v-else-if="modelState === 'pending'"
        state="loading"
        title="预测快照未就绪"
        :description="(modelError || '预测快照生成中。') + ' 页面只读取预生成结果、不运行模型；生成完成后自动显示。'"
      >
        <button type="button" class="frp-inline-btn" data-role="model-retry" @click="$emit('retry-model')">立即重试</button>
      </StatePanel>
      <StatePanel
        v-else-if="modelState === 'error' || !modelForecast"
        state="error"
        title="算法模型暂不可用"
        :description="modelError || '模型运行包或实时输入不可用。'"
      >
        <button type="button" class="frp-inline-btn" data-role="model-retry" @click="$emit('retry-model')">重试模型</button>
      </StatePanel>
      <template v-else>
        <!-- 全湖主结果 = 实际活跃站聚合；站点层尚未补齐时如实等待，绝不用全湖虚拟实体顶替 -->
        <div v-if="lakeAggregatePending" class="frp-agg-pending" data-role="lake-aggregate-pending">
          <b>全湖聚合生成中</b>
          <span>
            全湖主结果由 {{ lakeStationCount ?? "—" }} 站预测分布聚合得出；站点层补齐中（{{ lakeAggregatePending.done }}/{{ lakeAggregatePending.total }} 站），
            完成后自动显示。当前不展示"均值虚拟站点"口径的替代数值。
          </span>
        </div>
        <!-- 焦点指标 hero：全湖 = 活跃站聚合中位；站点 = 本站模型预测 -->
        <div v-else class="frp-hero" data-role="model-primary-result">
          <div class="frp-hero-main">
            <div class="frp-hero-value">
              <b>{{ primaryPrediction }}</b>
            </div>
            <div class="frp-hero-label">{{ metricLabel }}</div>
            <div class="frp-hero-scope" data-role="hero-scope-label">{{ heroScopeLabel }}</div>
            <div v-if="heroBar" class="frp-bandbar" :title="heroBar.title">
              <div class="frp-bandbar-track">
                <template v-if="heroBar.bands">
                  <i
                    v-for="(seg, i) in heroBar.bands"
                    :key="i"
                    class="frp-bandbar-seg"
                    :style="{ left: `${seg.left}%`, width: `${seg.width}%`, background: seg.color }"
                  ></i>
                </template>
                <i v-else class="frp-bandbar-line" :style="{ background: heroBar.color }"></i>
                <i class="frp-bandbar-marker" :style="{ left: `${heroBar.pct}%` }"></i>
              </div>
              <div v-if="heroBar.scaleLabels" class="frp-bandbar-scale">
                <span v-for="s in heroBar.scaleLabels" :key="s.text" :style="{ left: `${s.pct}%` }">{{ s.text }}</span>
              </div>
            </div>
          </div>
          <div v-if="riskRing" class="frp-ring" role="img" :aria-label="`风险概率 ${riskRing.pct}%`">
            <svg viewBox="0 0 72 72" width="72" height="72">
              <circle cx="36" cy="36" r="30" fill="none" stroke="rgba(127,147,168,0.18)" stroke-width="7" />
              <circle
                cx="36" cy="36" r="30" fill="none"
                :stroke="riskRing.color" stroke-width="7" stroke-linecap="round"
                :stroke-dasharray="`${riskRing.dash} 999`"
                transform="rotate(-90 36 36)"
              />
              <text x="36" y="41" text-anchor="middle" class="frp-ring-text">{{ riskRing.pct }}%</text>
            </svg>
            <span class="frp-ring-label">{{ scope === 'lake' ? '全湖中位风险概率' : '水华风险概率' }}</span>
          </div>
        </div>
        <div v-if="horizonTrend" class="frp-horizon" data-role="horizon-trend">
          <div class="frp-compare-head">
            <b>{{ horizonTrendTitle }}</b>
            <span>{{ horizonTrend.legend }}</span>
          </div>
          <svg viewBox="0 0 420 126" width="100%" height="126" preserveAspectRatio="none" role="img" :aria-label="`${metricLabel}七时效趋势`">
            <line x1="18" y1="82" x2="402" y2="82" class="frp-trend-axis" />
            <line :x1="horizonTrend.scenarioX" :x2="horizonTrend.scenarioX" y1="8" y2="88" class="frp-trend-split" />
            <polygon v-if="horizonTrend.band" :points="horizonTrend.band" class="frp-trend-band" />
            <polyline v-if="horizonTrend.lineShort" :points="horizonTrend.lineShort" class="frp-trend-line" />
            <polyline v-if="horizonTrend.lineScenario" :points="horizonTrend.lineScenario" class="frp-trend-line frp-trend-line--scenario" />
            <!-- 短期四档映射同一月标签，数值按定义相同：不画成四个独立点，合并为一段同月区间 -->
            <template v-if="horizonTrend.shortGroup">
              <rect
                :x="horizonTrend.shortGroup.x1" :y="horizonTrend.shortGroup.y - 5"
                :width="horizonTrend.shortGroup.x2 - horizonTrend.shortGroup.x1" height="10"
                rx="5" class="frp-trend-group" data-role="short-merged-group"
              ><title>{{ horizonTrend.shortGroup.title }}</title></rect>
              <text
                :x="(horizonTrend.shortGroup.x1 + horizonTrend.shortGroup.x2) / 2" y="113"
                text-anchor="middle" class="frp-trend-note" data-role="short-merged-label"
              >同月短期结果 · 四档同值</text>
            </template>
            <g v-else v-for="p in horizonTrend.shortPoints" :key="`sh${p.horizon}`">
              <circle :cx="p.x" :cy="p.y" r="4" class="frp-trend-point" :data-origin="p.originKey" :data-scenario="String(p.scenario)"><title>{{ p.title }}</title></circle>
            </g>
            <g v-for="p in horizonTrend.scenarioPoints" :key="`sc${p.horizon}`">
              <circle :cx="p.x" :cy="p.y" r="4" class="frp-trend-point" :data-origin="p.originKey" :data-scenario="String(p.scenario)" :data-station-resolution="String(p.stationResolution)"><title>{{ p.title }}</title></circle>
              <text :x="p.x" y="113" text-anchor="middle" class="frp-trend-note" :data-resolution="String(p.stationResolution)">{{ p.shortNote }}</text>
            </g>
            <g v-for="p in horizonTrend.points" :key="`l${p.horizon}`">
              <text :x="p.x" y="97" text-anchor="middle" class="frp-trend-label">+{{ p.horizon }}</text>
            </g>
            <text x="22" y="13" class="frp-trend-caption">短期</text>
            <text :x="horizonTrend.scenarioX + 6" y="13" class="frp-trend-caption">中长期</text>
          </svg>
          <p v-if="horizonTrend.resolutionNote" class="frp-unc-note" data-role="trend-resolution-note">
            {{ horizonTrend.resolutionNote }}
          </p>
          <ul v-if="horizonTrend.stationNotes.length" class="frp-unc-note" data-role="trend-station-notes">
            <li v-for="note in horizonTrend.stationNotes" :key="note">{{ note }}</li>
          </ul>
        </div>
        <p v-else-if="lakeAreaNote" class="frp-note" data-role="lake-area-note">{{ lakeAreaNote }}</p>

        <p v-if="scope === 'station' && modelForecast.quality_gate?.status !== 'ok'" class="frp-quality-flag" data-role="quality-gate" :title="modelForecast.quality_gate?.reason">当前结果需谨慎使用</p>

        <!-- 站点模式：九任务状态矩阵（本站模型输出） -->
        <template v-if="scope === 'station'">
          <h4 class="frp-sub-h">本次模型输出 <span>9 任务同一时效</span></h4>
          <div class="frp-cards" data-role="model-results">
            <div v-for="card in overviewCards" :key="card.key" class="frp-card" :title="card.title">
              <div class="frp-card-head">
                <span class="frp-card-label">{{ card.label }}</span>
              </div>
              <div class="frp-card-value">{{ card.text }}</div>
              <div v-if="card.bar != null" class="frp-card-bar">
                <i :style="{ width: `${Math.min(100, card.bar * 100)}%`, background: card.barColor }"></i>
              </div>
              <div v-else class="frp-card-bar frp-card-bar--empty"></div>
            </div>
          </div>
        </template>
        <!-- 全湖模式：活跃站聚合指标卡（主结果），不是全湖虚拟实体的模型输出 -->
        <template v-else-if="lakeCards.length">
          <h4 class="frp-sub-h">全湖聚合 · {{ lakeStationCount ?? "—" }} 站分布 <span>主结果口径</span></h4>
          <div class="frp-cards" data-role="lake-aggregate-cards">
            <div v-for="card in lakeCards" :key="card.key" class="frp-card" :title="card.title">
              <div class="frp-card-head">
                <span class="frp-card-label">{{ card.label }}</span>
              </div>
              <div class="frp-card-value">{{ card.text }}</div>
              <div v-if="card.bar != null" class="frp-card-bar">
                <i :style="{ width: `${Math.min(100, card.bar * 100)}%`, background: card.barColor }"></i>
              </div>
              <div v-else class="frp-card-bar frp-card-bar--empty"></div>
            </div>
          </div>
        </template>

        <!-- 预测 vs MEE 实测对照（叶绿素 a） -->
        <div v-if="chlaCompare" class="frp-compare" data-role="chla-compare">
          <div class="frp-compare-head"><b>预测与当前观测</b><span>叶绿素 a</span></div>
          <div class="frp-compare-row">
            <span class="frp-compare-name">模型预测</span>
            <div class="frp-compare-track">
              <i :style="{ width: `${chlaCompare.predPct}%`, background: chlaCompare.predColor }"></i>
            </div>
            <span class="frp-compare-val">{{ chlaCompare.predText }}</span>
          </div>
          <div class="frp-compare-row">
            <span class="frp-compare-name">当前 MEE 观测</span>
            <div class="frp-compare-track">
              <i class="frp-compare-obs" :style="{ width: `${chlaCompare.obsPct}%` }"></i>
            </div>
            <span class="frp-compare-val">{{ chlaCompare.obsText }}</span>
          </div>
        </div>

      </template>

      <template v-if="scope === 'station'">
        <h4 class="frp-sub-h">站点最新关键观测 <span>{{ stationObservedAt }}</span></h4>
        <dl v-if="stationKeyRows.length" class="frp-kv" data-role="station-obs">
          <div v-for="row in stationKeyRows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd :class="{ 'frp-miss': row.miss }">{{ row.text }}</dd>
          </div>
        </dl>
        <dl v-if="stationVsLake" class="frp-kv" data-role="station-vs-lake">
          <div>
            <dt>本站{{ metricLabel }} vs 全湖中位（{{ lakeStationCount ?? "—" }} 站）</dt>
            <dd>{{ stationVsLake.text }}</dd>
          </div>
        </dl>
      </template>
      <template v-else>
        <!-- 全湖汇总：活跃站预测分布聚合（替代"均值虚拟站点"口径） -->
        <div v-if="aggregate" class="frp-agg" data-role="lake-aggregate">
          <h4 class="frp-sub-h">全湖汇总 · {{ lakeStationCount ?? "—" }} 站分布聚合 <span>中位数 [P25, P75]</span></h4>
          <dl class="frp-kv">
            <div v-for="row in aggregateRows" :key="row.key">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.text }}</dd>
            </div>
            <div v-if="aggregateBloomShare">
              <dt>风险站占比（叶绿素a≥{{ aggregateBloomShare.threshold }}μg/L）</dt>
              <dd>{{ aggregateBloomShare.text }}</dd>
            </div>
            <div>
              <dt>站点覆盖</dt>
              <dd>{{ aggregate.coverage?.reported ?? '—' }}/{{ aggregate.coverage?.total ?? '—' }} 站</dd>
            </div>
          </dl>
          <p class="frp-agg-note">全湖指标由站点预测分布聚合得出，不是"均值虚拟站点"的模型输出。</p>
        </div>
        <h4 class="frp-sub-h">MEE 最新实测参考</h4>
        <dl class="frp-kv" data-role="observed-inputs">
          <div><dt>叶绿素 a 现状</dt><dd>{{ inputs.chlaText }}<i v-if="inputs.chlaTrend" class="frp-trend">{{ inputs.chlaTrend }}</i></dd></div>
          <div><dt>水温</dt><dd>{{ inputs.tempText }}</dd></div>
          <div><dt>总磷 / 总氮</dt><dd>{{ inputs.nutrientText }}</dd></div>
        </dl>
      </template>

    </div>

    <!-- ===== 驱动因素 ===== -->
    <div v-else-if="activeTab === 'drivers'" class="frp-body" role="tabpanel" aria-label="驱动因素" data-role="result-drivers">
      <!-- 全湖作用域：实际活跃站驱动因素分布（环境状态口径，不是虚拟站点条形卡） -->
      <LakeDriverDistribution v-if="scope === 'lake'" :horizon-days="horizonDays" />
      <!-- 站点作用域：机理净生长率分解（本站输入），模型无关、恒可用 -->
      <template v-else-if="mechanismDrivers">
        <div class="frp-driver-head">
          <div><b>水华形成驱动</b><span>环境 × 营养盐 × 水动力 × AI 响应</span></div>
          <strong v-if="mechanismNet" :class="mechanismNet.positive ? 'frp-net-up' : 'frp-net-down'">{{ mechanismNet.text }}</strong>
        </div>
        <p v-if="sourceGroups.note" class="frp-unc-note" data-role="driver-source-groups">{{ sourceGroups.note }}</p>
        <div class="frp-driver-modules" data-role="mechanism-factors">
          <section v-for="group in driverGroups" :key="group.key" class="frp-driver-module" :data-group="group.key">
            <header><i>{{ group.icon }}</i><div><b>{{ group.title }}</b><span>{{ group.subtitle }}</span></div></header>
            <div v-for="f in group.factors" :key="f.key" class="frp-factor-row" :data-factor="f.key">
              <div class="frp-factor-label">
                <span>{{ f.shortLabel }}</span>
                <b>{{ f.pctText }}</b>
              </div>
              <div class="frp-bar-track"><i class="frp-factor-fill" :style="{ width: `${f.stateOnly ? 4 : Math.max(f.pct, 4)}%`, background: f.color }"></i></div>
              <small data-role="driver-source">
                <em :data-resolution="f.stationResolution ? 'station' : 'lake'">{{ f.stationResolution ? '逐站' : '全湖' }}</em>
                {{ f.stateOnly ? (f.sourceText || '暂无量化') : f.sourceText }}
                <template v-if="f.saturated">（已取到上限，恒为 1.0）</template>
              </small>
            </div>
          </section>
        </div>
        <div v-if="mechanismLimiting" class="frp-limit" data-role="mechanism-limiting">
          <span>当前限制因子</span><b>{{ mechanismLimiting.label }} · {{ mechanismLimiting.pctText }}</b>
        </div>
        <div v-if="mechanismNet" class="frp-net" data-role="mechanism-net">
          <div class="frp-net-head">
            <b>综合净生长状态</b>
            <span :class="mechanismNet.positive ? 'frp-net-up' : 'frp-net-down'">
              {{ mechanismNet.positive ? '藻类净增长状态' : '藻类衰减状态' }}
            </span>
          </div>
          <div class="frp-net-track">
            <i class="frp-net-zero" aria-hidden="true"></i>
            <i
              class="frp-net-fill"
              :class="mechanismNet.positive ? 'frp-net-fill--up' : 'frp-net-fill--down'"
              :style="mechanismNet.style"
            ></i>
          </div>
          <div class="frp-net-scale"><span>−0.16 衰减</span><span>0</span><span>+0.6 增长</span></div>
        </div>
      </template>

      <section class="frp-ai-module">
        <div class="frp-driver-head frp-driver-head--small"><div><b>AI 响应排序</b><span>输入变化对当前输出的影响</span></div></div>
        <template v-if="modelExplanation?.effective">
        <ul class="frp-bars" data-role="driver-bars">
          <li v-for="f in modelFactors" :key="f.feature">
            <span class="frp-bar-label">{{ f.label }}</span>
            <span class="frp-bar-track">
              <i class="frp-bar-warm" :style="{ width: barWidth(f.contribution_percent) }"></i>
            </span>
            <span class="frp-bar-value">{{ Number(f.baseline).toLocaleString('zh-CN', { maximumFractionDigits: 3 }) }}<small>{{ f.direction === 'increase' ? '↑' : f.direction === 'decrease' ? '↓' : '→' }} {{ f.contribution_percent }}%</small></span>
          </li>
        </ul>
        </template>
        <div v-else class="frp-ai-empty" data-role="drivers-ineffective">当前输出对输入扰动没有明显响应</div>
      </section>

      <template v-if="unavailableFactors.length">
        <h4 class="frp-sub-h">当前冻结特征契约缺口</h4>
        <ul class="frp-neutral" data-role="driver-neutral">
          <li v-for="n in unavailableFactors" :key="n.feature">
            <b>{{ n.label }}</b>
            <span>{{ n.action }}</span>
          </li>
        </ul>
      </template>
    </div>

    <!-- ===== 不确定性 ===== -->
    <div v-else class="frp-body" role="tabpanel" aria-label="不确定性" data-role="result-uncertainty">
      <!-- V0.3：区间刻度尺 + 覆盖率环 + 任务区间矩阵 -->
      <template v-if="v3Uncertainty">
        <div class="frp-driver-head" data-role="v3-conformal-result">
          <div><b>预测范围</b><span>P05 — 点预测 — P95</span></div>
          <strong :data-status="uncertaintyStatus.key">{{ uncertaintyStatus.shortTitle }}</strong>
        </div>
        <p class="frp-unc-note" data-role="uncertainty-status-detail">{{ uncertaintyStatus.detail }}</p>

        <!-- 等级范围（风险等级由叶绿素 a 区间映射）：不是数值区间，画范围条而非刻度尺。
             风险等级不是焦点任务（焦点 risk 映射到 probability），它的区间挂在同一次输出的
             risk_level 兄弟结果上；这里连同焦点区间一起给出，页头同时展示等级与概率时才闭合。 -->
        <template v-if="bandRangeUncertainty">
          <div class="frp-driver-head" data-role="risk-band-range-head">
            <div><b>风险等级范围</b><span>由叶绿素 a 预测区间映射</span></div>
            <strong :data-status="bandRangeUncertainty.structural_valid ? (bandRangeUncertainty.decision_usable ? 'usable' : 'watch') : 'invalid'">
              {{ bandRangeStatusText }}
            </strong>
          </div>
          <dl class="frp-unc-stats" data-role="derived-band-range">
            <div><dt>偏低情景</dt><dd>{{ bandText(bandRangeUncertainty.p05_band) }}</dd></div>
            <div class="active"><dt>当前等级</dt><dd>{{ bandText(bandRangeUncertainty.point_band) }}</dd></div>
            <div><dt>偏高情景</dt><dd>{{ bandText(bandRangeUncertainty.p95_band) }}</dd></div>
          </dl>
          <p class="frp-unc-note" data-role="derived-band-source">
            源区间（叶绿素 a）：{{ bandText(bandRangeUncertainty.source_interval?.p05, true) }} —
            {{ bandText(bandRangeUncertainty.source_interval?.p95, true) }} μg/L，
            测试样本 n={{ bandRangeUncertainty.source_interval?.test_n ?? '—' }}，
            校准状态 {{ calibrationText(bandRangeUncertainty.calibration_status) }}。
          </p>
        </template>

        <!-- 源区间未达决策可用：不画等级范围条，也不留空态，显式说明原因。 -->
        <div v-else-if="bandRangeBlocked" data-role="band-range-blocked">
          <div class="frp-driver-head">
            <div><b>风险等级范围</b><span>由叶绿素 a 预测区间映射</span></div>
            <strong data-status="invalid">不给出范围</strong>
          </div>
          <p class="frp-unc-note" data-role="band-range-blocked-note">{{ bandRangeBlocked.note }}</p>
          <p class="frp-unc-note" data-role="band-range-blocked-reason">
            原因：{{ calibrationBlockText(bandRangeBlocked) }}｜
            源区间叶绿素 a：{{ bandText(bandRangeBlocked.source_interval?.p05, true) }} —
            {{ bandText(bandRangeBlocked.source_interval?.p95, true) }} μg/L｜
            测试样本 n={{ bandRangeBlocked.test_n ?? '—' }}
            <template v-if="bandRangeBlocked.empirical_coverage != null">
              ｜经验覆盖率 {{ (Number(bandRangeBlocked.empirical_coverage) * 100).toFixed(2) }}%
              （验收线 {{ (Number(bandRangeBlocked.coverage_acceptance_min) * 100).toFixed(0) }}%）
            </template>
          </p>
        </div>

        <!-- 区间刻度尺：P05—点—P95 落在参考带上。
             结构不自洽（退化 / 点预测越界 / 非有限值）时不得画成正常区间。 -->
        <div v-if="intervalScale && intervalScale.structuralValid" class="frp-scale" data-role="interval-scale">
          <svg :viewBox="`0 0 300 52`" width="100%" height="52" preserveAspectRatio="none" aria-label="预测区间刻度尺">
            <rect
              v-for="(seg, i) in intervalScale.segments"
              :key="i"
              :x="seg.x" y="8" :width="seg.w" height="10"
              :fill="seg.color" opacity="0.35"
            />
            <rect
              :x="intervalScale.p05X" y="5"
              :width="Math.max(intervalScale.p95X - intervalScale.p05X, 2)" height="16"
              fill="rgba(56,189,232,0.28)" stroke="#38bdf8" stroke-width="1"
              rx="2"
            />
            <line
              :x1="intervalScale.pointX" :x2="intervalScale.pointX" y1="2" y2="24"
              :stroke="intervalScale.pointColor" stroke-width="2"
            />
            <text :x="intervalScale.pointX" y="34" text-anchor="middle" class="frp-scale-text">{{ intervalScale.pointText }}</text>
            <text :x="intervalScale.p05X" y="34" text-anchor="middle" class="frp-scale-text frp-scale-text--dim">P05</text>
            <text :x="intervalScale.p95X" y="34" text-anchor="middle" class="frp-scale-text frp-scale-text--dim">P95</text>
            <g v-if="intervalScale.obsX != null">
              <line :x1="intervalScale.obsX" :x2="intervalScale.obsX" y1="40" y2="52" stroke="#7dd3fc" stroke-width="2" />
              <text :x="intervalScale.obsX" y="51" text-anchor="middle" class="frp-scale-text" fill="#7dd3fc">实测</text>
            </g>
          </svg>
        </div>
        <dl v-if="intervalScale && intervalScale.structuralValid" class="frp-unc-stats" data-role="v3-conformal-quantiles">
          <div><dt>偏低情景</dt><dd>{{ conformalValue(v3Uncertainty.p05) }}</dd></div>
          <div class="active"><dt>当前预测</dt><dd>{{ conformalPoint }}</dd></div>
          <div><dt>偏高情景</dt><dd>{{ conformalValue(v3Uncertainty.p95) }}</dd></div>
        </dl>

        <p v-if="conformalProtocolNote" class="frp-unc-note" data-role="uncertainty-protocol-note">{{ conformalProtocolNote }}</p>

        <!-- 覆盖率环 + 任务区间矩阵 -->
        <div class="frp-unc-grid">
          <div class="frp-ring-card" data-role="coverage-ring">
            <svg viewBox="0 0 72 72" width="82" height="82">
              <circle cx="36" cy="36" r="30" fill="none" stroke="rgba(127,147,168,0.18)" stroke-width="7" />
              <circle
                cx="36" cy="36" r="30" fill="none"
                :stroke="coverageRing.color" stroke-width="7" stroke-linecap="round"
                :stroke-dasharray="`${coverageRing.dash} 999`"
                transform="rotate(-90 36 36)"
              />
              <text x="36" y="41" text-anchor="middle" class="frp-ring-text">{{ coverageRing.text }}</text>
            </svg>
            <div class="frp-ring-meta">
              <b>经验覆盖率</b>
              <span>{{ coverageRing.note }}</span>
            </div>
          </div>
          <div class="frp-matrix" data-role="uncertainty-matrix">
            <b class="frp-matrix-title">各任务不确定性</b>
            <div class="frp-matrix-grid">
              <span
                v-for="m in uncertaintyMatrix"
                :key="m.key"
                class="frp-matrix-cell"
                :data-origin="m.originKey"
                :title="m.title"
              >{{ m.label }}<small>{{ m.statusText }}</small><i v-if="m.width" class="frp-matrix-width" :style="{ width: m.width }"></i></span>
            </div>
            <div class="frp-matrix-legend"><span>可用</span><span>校准证据不足</span><span>结构不自洽</span><span>退化/过宽</span><span>无</span></div>
          </div>
        </div>
      </template>

      <!-- legacy V0.2 输入扰动情景分布 -->
      <template v-if="legacyPerturbation">
        <div class="frp-method" data-role="uncertainty-result">
          <b>输入扰动情景分布 · {{ legacyPerturbation.sample_count }} 次</b>
          <span>{{ legacyPerturbation.note }}</span>
        </div>
        <dl v-if="legacyPerturbation.p50 != null" class="frp-kv" data-role="uncertainty-quantiles">
          <div><dt>P05</dt><dd>{{ uncertaintyValue(legacyPerturbation.p05) }}</dd></div>
          <div><dt>P50（中位数）</dt><dd>{{ uncertaintyValue(legacyPerturbation.p50) }}</dd></div>
          <div><dt>P95</dt><dd>{{ uncertaintyValue(legacyPerturbation.p95) }}</dd></div>
          <div><dt>标准差</dt><dd>{{ uncertaintyValue(legacyPerturbation.std) }}</dd></div>
        </dl>
      </template>

      <div v-if="!v3Uncertainty" class="frp-blocked" data-role="uncertainty-blocked">
        <b>{{ v3Forecast ? '当前任务未提供预测区间' : '该结果未提供预测区间' }}</b>
        <span>{{ v3Forecast
          ? '该任务当前没有 split-conformal 预测区间输出；若展示 P05—P95，均为输入扰动情景范围，不是预测区间。'
          : '当前结果量化的是输入变化下的模型响应；交付包没有真实测试残差区间，因此页面不会把 P05—P95 情景范围写成预测区间。' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
// 时空推演右侧预测结果面板：结果总览 / 驱动因素 / 不确定性 三标签。
// 总览=焦点 hero + 六宫格卡 + 预测/实测对照；驱动=机理净生长率分解（恒可用）+ 模型敏感性；
// 不确定性=conformal 区间刻度尺 + 覆盖率环 + 9 任务区间矩阵。
import { computed, ref, watch } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import LakeDriverDistribution from './LakeDriverDistribution.vue'
import { predictionSnapshot } from '../../stores/predictionSnapshot.js'

const props = defineProps({
  scope: { type: String, default: 'lake' }, // lake | station
  stationName: { type: String, default: '' },
  // 选中预测时刻 { title, sub }
  stop: { type: Object, default: null },
  // 预测指标重点：risk | chla | area | biomass
  metric: { type: String, default: 'risk' },
  // 全湖规则研判结果（riskAssessment.assess* 输出）
  assessment: { type: Object, default: null },
  // 站点规则研判结果（assessStationFactors 输出）
  stationAssessment: { type: Object, default: null },
  // 站点最新观测行（observed）
  stationRows: { type: Array, default: () => [] },
  // 全湖指标输入文本 { chlaText, chlaValue, chlaTrend, tempText, nutrientText }
  inputs: { type: Object, default: () => ({}) },
  // 站点环比变化摘要（实测参考）：左侧「站点环比变化」图层开启时显示
  diffEnabled: { type: Boolean, default: false },
  // { up, down, flat, top: [{ id, name, delta }] }
  diffSummary: { type: Object, default: () => ({ up: 0, down: 0, flat: 0, top: [] }) },
  diffRows: { type: Array, default: () => [] },
  diffBaseTime: { type: String, default: '上一快照' },
  // MEE 实时观测汇总加载中：研判未生成时显示加载态而非错误态
  summaryLoading: { type: Boolean, default: false },
  modelForecast: { type: Object, default: null },
  modelState: { type: String, default: 'loading' },
  modelError: { type: String, default: '' },
  // V0.3 真实数据包同时效预测（月度标签粒度 + conformal 区间）；null 时隐藏 V0.3 板块
  v3Forecast: { type: Object, default: null },
  // 同对象、同指标的 1/3/7/15/30/60/90 天响应，用于跨时效对照；各点保留自身来源标签
  horizonForecasts: { type: Array, default: () => [] },
  // 全湖聚合层（station_aggregate）：全湖指标由活跃站预测分布聚合，仅 lake 作用域展示
  aggregate: { type: Object, default: null },
  // 当前预测时效（驱动因素分布等随快照时效取数）
  horizonDays: { type: Number, default: 1 }
})

defineEmits(['back-to-lake', 'retry', 'retry-model'])

const FOCUS_KEY_BY_METRIC = { risk: 'probability', chla: 'chla', area: 'area', biomass: 'biomass', density: 'density' }

const TABS = [
  { key: 'overview', label: '结果总览' },
  { key: 'drivers', label: '驱动因素' },
  { key: 'uncertainty', label: '不确定性' }
]
const activeTab = ref('overview')

const diffVisualRows = computed(() => {
  const comparable = props.diffRows.filter((row) => row.previous != null && row.current != null)
  if (!comparable.length) return []
  const max = Math.max(...comparable.flatMap((row) => [Number(row.previous), Number(row.current)]), 1)
  return comparable
    .slice()
    .sort((a, b) => Math.abs(Number(b.delta)) - Math.abs(Number(a.delta)))
    .slice(0, 8)
    .map((row) => {
      const beforePct = Math.max(2, Math.min(98, Number(row.previous) / max * 100))
      const afterPct = Math.max(2, Math.min(98, Number(row.current) / max * 100))
      return {
        ...row,
        beforePct,
        afterPct,
        linkStyle: { left: `${Math.min(beforePct, afterPct)}%`, width: `${Math.max(Math.abs(afterPct - beforePct), 1)}%` },
        deltaText: row.status === 'flat' ? '持平' : `${row.delta > 0 ? '+' : ''}${row.delta}`
      }
    })
})

const METRIC_LABELS = { risk: '风险等级', chla: '叶绿素 a', area: '水华面积', biomass: '蓝藻生物量' }
const METRIC_KEYS = { risk: 'probability', chla: 'chla', area: 'area', biomass: 'biomass' }
const metricLabel = computed(() => METRIC_LABELS[props.metric] || props.metric)

// ---- 风险带口径（V0.3 risk_bands_ug_l 同源） ----
const BANDS = [
  { max: 10, color: '#5fd6a4', label: 'I' },
  { max: 20, color: '#a3d977', label: 'II' },
  { max: 30, color: '#f5b45d', label: 'III' },
  { max: 50, color: '#ef4444', label: 'IV' },
  { max: Infinity, color: '#b91c1c', label: 'V' }
]
function bandColorOf(value) {
  return BANDS.find((b) => value < b.max)?.color || '#b91c1c'
}
function bandSegments(domainMax) {
  const segs = []
  let low = 0
  for (const b of BANDS) {
    if (low >= domainMax) break
    const high = Math.min(b.max, domainMax)
    segs.push({ left: (low / domainMax) * 100, width: ((high - low) / domainMax) * 100, color: b.color })
    low = b.max
  }
  return segs
}

// ---- 焦点任务 ----
const focusResult = computed(() => {
  const key = props.modelForecast?.analysis_focus?.result_key
  return key ? props.modelForecast?.results?.[key] : null
})

// ---------- 全湖口径闭环：lake 模式主结果 = 79 站聚合（station_aggregate） ----------
// 全湖模式一律读聚合层；"均值虚拟站点"的模型输出不再具备主展示资格。
const lakeAggregate = computed(() => props.aggregate || null)
const lakeAggregateReady = computed(() => Boolean(lakeAggregate.value?.metrics))
// 站点分母动态化（审计整改 2026-09-12）：目录 79 站、当轮活跃可能只有 78，
// 所有"79 站"字样必须读实际聚合分母，禁止写死。
const lakeStationCount = computed(() =>
  lakeAggregate.value?.station_total
  ?? predictionSnapshot.status?.stations?.total
  ?? null
)
const focusMetricKey = computed(() => FOCUS_KEY_BY_METRIC[props.metric] || 'probability')
const aggregateMetric = (key) => lakeAggregate.value?.metrics?.[key] || null
// 站点层尚未补齐（快照分两阶段发布）：全湖模式如实等待聚合层，不用虚拟站点数值顶替。
const lakeAggregatePending = computed(() => {
  if (props.scope !== 'lake' || lakeAggregateReady.value) return null
  const stations = predictionSnapshot.status?.stations || {}
  return { done: stations.done ?? 0, total: stations.total ?? 0 }
})
const RISK_LEVEL_TEXT = { none: '无', low: '低', medium: '中', high: '高', severe: '严重' }
// 全湖面积口径：月度遥感反演现值（记录自带 value_origin_note），不随时效外推、不从站点相加。
const lakeAreaResult = computed(() =>
  props.scope === 'lake' && props.metric === 'area' ? props.modelForecast?.results?.area || null : null
)
const lakeAreaNote = computed(() => {
  if (!lakeAreaResult.value) return ''
  return `水华面积为最近一期月度遥感反演现值（${lakeAreaResult.value.value_origin_note || '月度反演场边界面积'}），不随时效外推，因此不绘制趋势线。`
})
// T+30 起为中长期月度趋势档：来源可能是逐站模型（T+90）或季节气候态基线（T+30/60），
// 主结果上必须带口径徽标说清是哪一种，不能笼统写成"未验证"——两者都有真实来源与回测。
const isLongTermHorizon = computed(() => Number(props.horizonDays) >= 30)
// 2026-09-12 复审整改：T+90 并非所有指标都有站点响应——叶绿素 a 是逐站模型（48 站不同值），
// 而概率/生物量/密度在补训时选中的是 climatology_global 全局常量模型：读的是模型文件，
// 但模型输入不随站点变化。站点语义必须来自快照的指标级三态诊断（按时效桶），
// 不得从"不是季节基线"倒推"逐站"。
function horizonStationResolution(metric, horizonDays) {
  const key = METRIC_KEYS[metric] || metric
  const entry = predictionSnapshot.metricDiagnostics?.[key]
  if (!entry) return null
  const h = Number(horizonDays)
  if ((entry.non_responsive_horizons || []).includes(h)) return false
  if ((entry.responsive_horizons || []).includes(h) && (entry.variation_horizons || []).includes(h)) return true
  return null
}
const longTermTag = computed(() => {
  const item = props.modelForecast?.results?.[METRIC_KEYS[props.metric]]
  if (!item || item.value == null) return '中长期月度趋势'
  if (item.value_origin === 'seasonal_climatology_baseline') return '中长期 · 季节气候态（全湖同值）'
  const res = horizonStationResolution(props.metric, props.horizonDays)
  if (res === false) return '中长期 · 全湖常量模型（无站点响应）'
  if (res === true) return '中长期月度趋势 · 逐站模型'
  return '中长期月度趋势'
})
const heroScopeLabel = computed(() => {
  if (props.scope === 'station') {
    if (props.metric === 'area') return '全湖遥感反演值（不随站点变化）'
    return isLongTermHorizon.value ? longTermTag.value : '本站模型预测'
  }
  if (props.metric === 'area') return '全湖 · 月度遥感反演现值'
  // 站点分母读聚合层实际值（目录 79 站、当轮活跃可能只有 78）——不得写死。
  const base = lakeAggregateReady.value
    ? `全湖 · ${lakeAggregate.value?.station_total ?? '—'} 站聚合中位数`
    : '全湖'
  return isLongTermHorizon.value ? `${base} · ${longTermTag.value}` : base
})

// ---- hero：焦点值 + 参考带刻度条 / 风险环 ----
const UNIT_TEXT = { rank: '秩', ratio: '' }
function fmtValue(item, digits = 3, percent = false) {
  const raw = item?.value
  if (raw == null || Number.isNaN(Number(raw))) return { value: '—', unit: '' }
  const numeric = Number(raw) * (percent ? 100 : 1)
  const unit = percent ? '%' : (UNIT_TEXT[item.unit] ?? item.unit ?? '')
  return {
    value: numeric.toLocaleString('zh-CN', { maximumFractionDigits: digits }),
    unit
  }
}
const heroBar = computed(() => {
  // 全湖模式：参考带作用在聚合中位数上
  if (props.scope === 'lake' && props.metric !== 'area') {
    const stats = aggregateMetric(focusMetricKey.value)
    if (!stats || stats.median == null) return null
    const v = Number(stats.median)
    if (props.metric === 'chla') {
      const domainMax = Math.max(50, v * 1.15)
      return {
        pct: Math.min(100, (v / domainMax) * 100),
        bands: bandSegments(domainMax),
        scaleLabels: BANDS.filter((b) => b.max !== Infinity && b.max <= domainMax)
          .map((b) => ({ pct: (b.max / domainMax) * 100, text: String(b.max) })),
        title: `79 站中位数在叶绿素 a 风险带刻度上的位置（μg/L）：${v}`
      }
    }
    if (props.metric === 'risk') {
      return { pct: Math.min(100, v * 100), color: bandColorOf(v * 50), title: `全湖中位风险概率：${(v * 100).toFixed(1)}%` }
    }
    if (props.metric === 'biomass') {
      return { pct: Math.min(100, (v / 10) * 100), color: '#38bdf8', title: '79 站中位（参考轴 0–10 mg/L）' }
    }
    return null
  }
  const key = METRIC_KEYS[props.metric]
  const item = props.modelForecast?.results?.[key]
  const raw = item?.value
  if (raw == null || Number.isNaN(Number(raw))) return null
  const v = Number(raw)
  if (props.metric === 'chla') {
    const domainMax = Math.max(50, v * 1.15)
    return {
      pct: Math.min(100, (v / domainMax) * 100),
      bands: bandSegments(domainMax),
      scaleLabels: BANDS.filter((b) => b.max !== Infinity && b.max <= domainMax)
        .map((b) => ({ pct: (b.max / domainMax) * 100, text: String(b.max) })),
      title: `叶绿素 a 风险带刻度（μg/L）：${v}`
    }
  }
  if (props.metric === 'risk') {
    return {
      pct: Math.min(100, v * 100),
      color: bandColorOf(v * 50),
      title: `水华发生概率：${(v * 100).toFixed(1)}%`
    }
  }
  if (props.metric === 'biomass') {
    return { pct: Math.min(100, (v / 10) * 100), color: '#38bdf8', title: '参考轴 0–10 mg/L' }
  }
  if (props.metric === 'area') {
    const retrieval = props.modelForecast?.results?.area?.value_origin === 'derived_from_monthly_retrieval_field'
    return {
      pct: Math.min(100, (v / 2338.4) * 100),
      color: '#38bdf8',
      scaleLabels: [{ pct: 0, text: '0' }, { pct: 50, text: '湖面50%' }, { pct: 100, text: '2338.4' }],
      title: retrieval
        ? `月度遥感反演水华面积 ${v.toFixed(2)} km²，约占太湖参考面积 ${(v / 2338.4 * 100).toFixed(2)}%`
        : `合成情景面积 ${v.toFixed(3)} km²，约占太湖参考面积 ${(v / 2338.4 * 100).toFixed(2)}%`
    }
  }
  return null
})
const riskRing = computed(() => {
  // 全湖模式：环 = 79 站中位风险概率
  const prob = props.scope === 'lake'
    ? aggregateMetric('probability')?.median
    : props.modelForecast?.results?.probability?.value
  if (prob == null || Number.isNaN(Number(prob))) return null
  const pct = Math.round(Number(prob) * 1000) / 10
  return {
    pct,
    dash: `${(Math.min(pct, 100) / 100) * 188.5} `,
    color: pct >= 50 ? '#ef4444' : pct >= 25 ? '#f5b45d' : pct >= 10 ? '#a3d977' : '#5fd6a4'
  }
})

// ---- 六宫格指标卡 ----
// 2026-09-12 复审整改：不得把补训结果统一写成"真实·补训"——标签来源必须按
// label_provenance 区分实测/混合/代理，代理与混合不得被读成纯实测。
function provenanceBadge(item) {
  const p = String(item?.label_provenance || '')
  if (!p) return ''
  if (p.startsWith('mixed') || (p.includes('ground_truth') && p.includes('proxy'))) return '混合标签'
  if (p.includes('ground_truth')) return '实测标签'
  if (p.includes('proxy')) return '代理标签'
  return ''
}
function originLabel(item) {
  if (!item || item.value == null) return '无输出'
  if (item.value_origin === 'legacy_v0_2_synthetic_fallback') return '合成对照'
  if (item.value_origin === 'derived_from_chla_v0_3_risk_bands') return '叶绿素推导'
  if (item.value_origin === 'derived_from_monthly_retrieval_field') return '遥感反演'
  if (item.value_origin === 'seasonal_climatology_baseline') return '季节气候态·全湖同值'
  if (item.training_protocol === 'train_internal_time_block_cv_v1') {
    const badge = provenanceBadge(item)
    return badge ? `补训模型·${badge}` : '补训模型'
  }
  return ''
}
function originKey(item) {
  if (!item || item.value == null) return 'none'
  if (item.value_origin === 'legacy_v0_2_synthetic_fallback') return 'legacy'
  if (item.value_origin === 'derived_from_chla_v0_3_risk_bands') return 'derived'
  if (item.value_origin === 'derived_from_monthly_retrieval_field') return 'rs'
  if (item.value_origin === 'seasonal_climatology_baseline') return 'climatology'
  if (item.training_protocol === 'train_internal_time_block_cv_v1') return 'cv'
  return 'real'
}
const overviewCards = computed(() => {
  const results = props.modelForecast?.results || {}
  const bloom = results.bloom
  const risk = results.probability
  const riskLevel = results.risk_level
  const chla = results.chla
  const coverage = results.coverage
  const density = results.density
  const biomass = results.biomass
  const area = results.area
  const spatial = results.spatial
  const bloomV = bloom?.value != null ? Number(bloom.value) : null
  const riskV = risk?.value != null ? Number(risk.value) : null
  const chlaV = chla?.value != null ? Number(chla.value) : null
  const covV = coverage?.value != null ? Number(coverage.value) : null
  const denV = density?.value != null ? Number(density.value) : null
  const bioV = biomass?.value != null ? Number(biomass.value) : null
  const areaV = area?.value != null ? Number(area.value) : null
  const spatialV = spatial?.value != null ? Number(spatial.value) : null
  return [
    {
      key: 'bloom', label: '水华发生',
      text: bloomV == null ? '—' : (bloomV >= 0.5 ? '发生' : '未发生'),
      bar: bloomV, barColor: bloomV >= 0.5 ? '#ef4444' : '#5fd6a4',
      origin: originLabel(bloom), originKey: originKey(bloom), title: 'T1 水华发生分类'
    },
    {
      key: 'risk', label: '风险概率',
      text: riskV != null ? `${(riskV * 100).toFixed(1)}%` : '—',
      bar: riskV,
      barColor: riskV != null ? bandColorOf(riskV * 50) : 'transparent',
      origin: originLabel(risk), originKey: originKey(risk),
      title: '水华发生概率（T1/T6 真实链路）'
    },
    {
      key: 'chla', label: '叶绿素 a',
      text: chlaV != null ? `${chlaV.toFixed(3)} μg/L` : '—',
      bar: chlaV != null ? Math.min(chlaV / 50, 1) : null,
      barColor: chlaV != null ? bandColorOf(chlaV) : 'transparent',
      origin: originLabel(chla), originKey: originKey(chla),
      title: '叶绿素 a 浓度（T5 真实链路，风险带 0–50 μg/L）'
    },
    {
      key: 'area', label: '水华面积',
      text: resultValue('area', 4),
      bar: areaV != null ? Math.min(areaV / 2338.4, 1) : null,
      barColor: '#38bdf8',
      origin: originLabel(area), originKey: originKey(area),
      title: areaV != null
        ? (area?.value_origin_note || `水华面积（${originLabel(area) || '全湖量'}），约占太湖 2338.4 km² 的 ${(areaV / 2338.4 * 100).toFixed(2)}%`)
        : '水华面积无输出'
    },
    {
      key: 'coverage', label: '水华覆盖率',
      text: covV != null ? `${(covV * 100).toFixed(2)}%` : '—',
      bar: covV,
      barColor: '#38bdf8',
      origin: originLabel(coverage), originKey: originKey(coverage),
      title: '湖面覆盖比例'
    },
    {
      key: 'density', label: '蓝藻密度',
      text: denV != null ? `${denV.toFixed(3)} 秩` : '—',
      bar: denV,
      barColor: '#a78bfa',
      origin: originLabel(density), originKey: originKey(density),
      title: '密度分位秩（0–1，T3 补训）'
    },
    {
      key: 'biomass', label: '蓝藻生物量',
      text: bioV != null ? `${bioV.toFixed(4)} mg/L` : '—',
      bar: bioV != null ? Math.min(bioV / 10, 1) : null,
      barColor: '#f5b45d',
      origin: originLabel(biomass), originKey: originKey(biomass),
      title: '生物量（T4 补训，参考轴 0–10 mg/L）'
    },
    {
      key: 'risk_level', label: '风险等级',
      text: riskLevelText.value,
      bar: riskV, barColor: riskV != null ? bandColorOf(riskV * 50) : 'transparent',
      origin: originLabel(riskLevel), originKey: originKey(riskLevel),
      title: '风险等级由叶绿素风险带推导；不是独立多分类模型概率'
    },
    {
      key: 'spatial', label: '空间范围',
      text: spatialV != null ? `${(spatialV * 100).toFixed(2)}%` : '—',
      bar: spatialV, barColor: '#22d3ee',
      origin: originLabel(spatial), originKey: originKey(spatial),
      title: '空间范围任务；无真实标签时显示合成对照或无输出'
    }
  ]
})
const riskLevelText = computed(() => {
  const value = props.modelForecast?.results?.risk_level?.value
  return RISK_LEVEL_TEXT[value] || value || '—'
})
// 全湖风险等级：聚合层按冻结风险带对 79 站 chla 中位数重新判级（不是站点等级平均）
const lakeRiskLevelText = computed(() => {
  const level = lakeAggregate.value?.risk_level_lake?.value
  return level ? (RISK_LEVEL_TEXT[level] || level) : '—'
})
function resultValue(key, digits = 2, percent = false) {
  const item = props.modelForecast?.results?.[key]
  const { value, unit } = fmtValue(item, digits, percent)
  return value === '—' ? '—' : `${value}${unit ? ` ${unit}` : ''}`
}
const primaryPrediction = computed(() => {
  // 全湖模式主结果 = 79 站聚合（面积 = 遥感反演现值）
  if (props.scope === 'lake' && !lakeAggregatePending.value) {
    if (props.metric === 'area') return resultValue('area', 4)
    const stats = aggregateMetric(focusMetricKey.value)
    if (!stats || stats.median == null) return '—'
    if (props.metric === 'risk') {
      const pct = (Number(stats.median) * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 })
      return `${lakeRiskLevelText.value} · ${pct}%`
    }
    const digits = props.metric === 'biomass' ? 4 : 3
    const unit = props.metric === 'biomass' ? ' mg/L' : ' μg/L'
    return `${Number(stats.median).toLocaleString('zh-CN', { maximumFractionDigits: digits })}${unit}`
  }
  if (props.metric === 'risk') return `${riskLevelText.value} · ${fmtValue(props.modelForecast?.results?.probability, 1, true).value}%`
  const digits = props.metric === 'area' || props.metric === 'biomass' ? 4 : 3
  return resultValue(props.metric, digits)
})

const HORIZONS = [1, 3, 7, 15, 30, 60, 90]
const SCENARIO_FROM = 30
const horizonTrendTitle = computed(() =>
  props.scope === 'lake' ? `${metricLabel.value} · 79 站中位趋势` : `${metricLabel.value}趋势`
)
const horizonTrend = computed(() => {
  // 全湖模式：各时效取 79 站聚合的中位数，带 = P25–P75 站间分布；
  // 站点模式：本站各时效模型输出，带 = conformal P05–P95。
  // 30 天起为情景推演口径：虚线绘制，不与短期真实预测混同一条线。
  const rows = HORIZONS.map((horizon) => {
    const suite = props.horizonForecasts.find((item) => Number(item?.horizon_days) === horizon)
    let value = null
    let bandLow = null
    let bandHigh = null
    let item = null
    let originKeyValue = 'agg'
    if (props.scope === 'lake') {
      if (props.metric === 'area') return null // 面积为遥感现值，不随时效外推，不画趋势
      const stats = (suite?.station_aggregate?.metrics || {})[focusMetricKey.value]
      if (!stats || stats.median == null) return null
      const scale = props.metric === 'risk' ? 100 : 1
      value = Number(stats.median) * scale
      bandLow = stats.p25 != null ? Number(stats.p25) * scale : null
      bandHigh = stats.p75 != null ? Number(stats.p75) * scale : null
    } else {
      item = suite?.results?.[METRIC_KEYS[props.metric]]
      const raw = Number(item?.value)
      if (!Number.isFinite(raw)) return null
      value = props.metric === 'risk' ? raw * 100 : raw
      originKeyValue = originKey(item)
      const u = item?.uncertainty
      // 趋势带的绘制门槛是「区间结构自洽 + 确为预测区间」，不是「校准有效」。
      // 校准证据与决策可用性由 PredictionDisclosure 单独披露，不得用画不画带子来暗示。
      const structuralValid = u?.is_prediction_interval !== false && Boolean(u?.structural_valid)
      bandLow = structuralValid && Number.isFinite(Number(u.p05)) ? Number(u.p05) * (props.metric === 'risk' ? 100 : 1) : null
      bandHigh = structuralValid && Number.isFinite(Number(u.p95)) ? Number(u.p95) * (props.metric === 'risk' ? 100 : 1) : null
    }
    const valueText = value.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
    const title = props.scope === 'lake'
      ? `T+${horizon}：79 站中位 ${valueText}${props.metric === 'risk' ? '%' : ''}${bandLow != null ? `（P25–P75：${bandLow.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}—${bandHigh.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}）` : ''}`
      : `T+${horizon}：${valueText}${props.metric === 'risk' ? '%' : ''} · ${originLabel(item) || 'V0.3真实链路'}`
    // 中长期两点必须逐点标注来源，否则"全湖同值"会被读成"逐站趋势"。
    // 常量全局模型（climatology_global）虽读取模型文件，但无站点响应，同样按全湖对待。
    const stationResolution = item
      ? (item.station_resolution != null
          ? Boolean(item.station_resolution)
          : item.value_origin === 'seasonal_climatology_baseline'
            ? false
            : horizonStationResolution(props.metric, horizon) === true)
      : null
    return {
      horizon, value, item,
      bandLow, bandHigh,
      scenario: horizon >= SCENARIO_FROM,
      originKey: originKeyValue,
      stationResolution,
      shortNote: stationResolution ? '逐站' : '全湖同值',
      title
    }
  })
  if (!rows.some(Boolean)) return null
  const values = rows.filter(Boolean).flatMap((row) => [row.value, row.bandLow, row.bandHigh].filter(Number.isFinite))
  const min = Math.min(0, ...values)
  const max = Math.max(...values, min + 1)
  const span = max - min || 1
  const x = (index) => 28 + index * 60
  const y = (value) => 78 - ((value - min) / span) * 58
  const points = rows.map((row, index) => row ? {
    ...row, x: x(index), y: y(row.value)
  } : null).filter(Boolean)
  // 带：只画结构自洽的预测区间。中长期点现在也有真实区间（逐站模型 conformal 或
  // 季节气候态留出残差分位数），不再因为"≥30 天"就被一刀切掉——没有区间的点自然不参与。
  const bandRows = points.filter((row) => row.bandLow != null && row.bandHigh != null)
  const upper = bandRows.map((row) => `${row.x},${y(row.bandHigh)}`)
  const lower = [...bandRows].reverse().map((row) => `${row.x},${y(row.bandLow)}`)
  // 线：短期实线；中长期段虚线并从最后一个短期点延续，保持视觉连续但口径分明。
  const shortPoints = points.filter((row) => !row.scenario)
  const scenarioPoints = points.filter((row) => row.scenario)
  const anchor = shortPoints.length ? shortPoints[shortPoints.length - 1] : null
  const scenarioLine = anchor ? [anchor, ...scenarioPoints] : scenarioPoints
  // 分辨率披露：1/3/7/15 天在标签上映射到同一个月，四档输出必然相同。
  // 关键改动（2026-09-11）：数值相同时**不再画四个点**——四个点看起来像四条独立预测，
  // 会让人误以为模型有日尺度信号。合并成一段"同月短期结果"区间，图上一眼可辨。
  const shortValues = shortPoints.map((row) => row.value)
  const shortFlat = shortValues.length >= 2 && shortValues.every((v) => Math.abs(v - shortValues[0]) < 1e-9)
  const shortGroup = shortFlat
    ? {
        x1: shortPoints[0].x - 16,
        x2: shortPoints[shortPoints.length - 1].x + 16,
        y: shortPoints[0].y,
        title: `同月短期结果 T+${shortPoints.map((p) => p.horizon).join('/')}：${shortValues[0].toLocaleString('zh-CN', { maximumFractionDigits: 3 })}（同一月度标签，四档按定义相同）`
      }
    : null
  const longOrigins = new Set(scenarioPoints.map((row) => row.originKey))
  const notes = []
  if (shortGroup) {
    notes.push('短期四档（T+1/3/7/15）共用同一个月度标签，数值按定义相同，图上合并标注为“同月短期结果”——训练面板为站-月粒度，不含日尺度信号。')
  }
  if (longOrigins.has('climatology')) {
    notes.push(
      scenarioPoints.some((p) => p.item?.seasonal_lookup_mode === 'global_fallback')
        ? '中长期虚线含季节气候态基线点：部分目标月无历史同期样本，该档使用全期均值基线（全湖同值、不含站点分辨）。'
        : '中长期虚线含季节气候态基线点：按目标月给出历史同期值，全湖同值、不含站点分辨。'
    )
  }
  // 逐点来源说明：让"哪一档能看站点差异"变成一条可核对的清单，而不是靠图例猜。
  const stationNotes = scenarioPoints.map((p) => {
    const label = `T+${p.horizon}`
    if (p.stationResolution === true) {
      const file = p.item?.model_file
      return `${label} 逐站月度趋势（${originLabel(p.item) || 'V0.3 模型'}${file ? ` · ${file}` : ''}），可做站间比较`
    }
    if (p.stationResolution === false) {
      if (p.item?.value_origin === 'seasonal_climatology_baseline') {
        const fallback = p.item?.seasonal_lookup_mode === 'global_fallback'
          ? '（目标月无同期样本，使用全期均值基线）'
          : ''
        return `${label} 全湖季节基线（季节气候态 · 全湖同值）${fallback}，不做站间比较`
      }
      return `${label} 全湖常量模型（读模型文件但无站点响应），不做站间比较`
    }
    return `${label} 来源未标注站点分辨率，按全湖同值对待`
  })
  return {
    points,
    shortPoints,
    scenarioPoints,
    shortGroup,
    lineShort: shortPoints.length >= 2 ? shortPoints.map((p) => `${p.x},${p.y}`).join(' ') : '',
    lineScenario: scenarioLine.length >= 2 ? scenarioLine.map((p) => `${p.x},${p.y}`).join(' ') : '',
    band: bandRows.length >= 2 ? [...upper, ...lower].join(' ') : '',
    scenarioX: 28 + 3.5 * 60,
    legend: shortGroup ? '同月短期（合并）· 中长期虚线（点位标注站点分辨率）' : '短期实线 · 中长期虚线',
    resolutionNote: notes.join(' '),
    stationNotes
  }
})

// ---- 预测 vs 实测对照（叶绿素 a） ----
const chlaCompare = computed(() => {
  // 全湖模式对照 79 站中位数；站点模式对照本站预测
  const pred = props.scope === 'lake'
    ? aggregateMetric('chla')?.median
    : props.modelForecast?.results?.chla?.value
  const obs = Number(props.inputs?.chlaValue)
  if (pred == null || !Number.isFinite(obs)) return null
  const domainMax = Math.max(50, Number(pred) * 1.15, obs * 1.15)
  return {
    predPct: Math.min(100, (Number(pred) / domainMax) * 100),
    predColor: bandColorOf(Number(pred)),
    predText: `${Number(pred).toFixed(3)} μg/L`,
    obsPct: Math.min(100, (obs / domainMax) * 100),
    obsText: `${obs.toFixed(2)} μg/L`
  }
})

// ---------- 全湖聚合指标卡：主结果口径（79 站分布） ----------
const lakeCards = computed(() => {
  const agg = lakeAggregate.value
  if (!agg?.metrics) return []
  const fmt = (v, d = 3) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: d })
  const prob = agg.metrics.probability
  const chla = agg.metrics.chla
  const bio = agg.metrics.biomass
  const den = agg.metrics.density
  const bloom = agg.chla_bloom_share
  const highShare = agg.probability_high_share
  const level = agg.risk_level_lake
  const cards = []
  if (prob?.median != null) {
    cards.push({
      key: 'probability', label: '风险概率中位',
      text: `${fmt(Number(prob.median) * 100, 1)}%`,
      bar: Number(prob.median), barColor: bandColorOf(Number(prob.median) * 50),
      title: `79 站中位；P25 ${fmt(Number(prob.p25) * 100, 1)}% / P75 ${fmt(Number(prob.p75) * 100, 1)}% / P90 ${prob.p90 != null ? `${fmt(Number(prob.p90) * 100, 1)}%` : '—'}`
    })
  }
  if (highShare) {
    cards.push({
      key: 'probability_high_share', label: '高风险站占比',
      text: `${Math.round(highShare.share * 100)}%`,
      bar: highShare.share, barColor: '#ef4444',
      title: `风险概率 ≥ ${highShare.threshold} 的站点 ${highShare.num}/${highShare.den} 站（与 T1 水华发生判据同阈值）`
    })
  }
  if (chla?.median != null) {
    cards.push({
      key: 'chla', label: '叶绿素 a 中位',
      text: `${fmt(chla.median)} μg/L`,
      bar: Math.min(Number(chla.median) / 50, 1), barColor: bandColorOf(Number(chla.median)),
      title: `79 站中位；P25 ${fmt(chla.p25)} / P75 ${fmt(chla.p75)} μg/L`
    })
  }
  if (bloom) {
    cards.push({
      key: 'chla_bloom_share', label: '风险站占比',
      text: `${Math.round(bloom.share * 100)}%`,
      bar: bloom.share, barColor: bandColorOf(bloom.threshold_ug_l),
      title: `叶绿素 a ≥ ${bloom.threshold_ug_l} μg/L 的站点 ${bloom.num}/${bloom.den} 站（与水华边界同阈值）`
    })
  }
  if (bio?.median != null) {
    const weighted = agg.biomass_area_weighted
    cards.push({
      key: 'biomass', label: '生物量中位',
      text: `${fmt(bio.median, 4)} mg/L`,
      bar: Math.min(Number(bio.median) / 10, 1), barColor: '#f5b45d',
      title: weighted
        ? `79 站中位；分区面积加权均值 ${fmt(weighted.value, 4)} mg/L（公示面积口径并列披露）`
        : '79 站中位；P25/P75 见下方汇总明细'
    })
  }
  if (den?.median != null) {
    cards.push({
      key: 'density', label: '密度中位',
      text: fmt(den.median),
      bar: Number(den.median), barColor: '#a78bfa',
      title: '密度分位秩 79 站中位（0–1）'
    })
  }
  if (level?.value) {
    cards.push({
      key: 'risk_level_lake', label: '全湖风险等级',
      text: RISK_LEVEL_TEXT[level.value] || level.value,
      bar: null, barColor: 'transparent',
      title: `冻结风险带作用于 79 站叶绿素 a 中位数（${fmt(level.chla_median_ug_l)} μg/L）重新判级；不是站点等级平均`
    })
  } else if (level?.reason) {
    cards.push({
      key: 'risk_level_lake', label: '全湖风险等级',
      text: '—',
      bar: null, barColor: 'transparent',
      title: level.note || '全湖判级依据（冻结风险带）不可读，如实缺省'
    })
  }
  const areaItem = props.modelForecast?.results?.area
  const areaV = areaItem?.value != null ? Number(areaItem.value) : null
  if (areaV != null && areaItem?.value_origin === 'derived_from_monthly_retrieval_field') {
    cards.push({
      key: 'area', label: '水华面积（遥感反演）',
      text: `${fmt(areaV, 2)} km²`,
      bar: Math.min(areaV / 2338.4, 1), barColor: '#38bdf8',
      title: areaItem?.value_origin_note || '最近一期月度遥感反演边界面积；不随时效外推'
    })
  }
  return cards
})

// ---- 驱动因素：机理分解（恒可用） ----
const mechanismDrivers = computed(() => (props.v3Forecast ? props.modelForecast?.mechanism_drivers : null))

// ---------- 全湖聚合层：79 站预测分布的站间摘要（station_aggregate） ----------
function fmtAgg(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}
const AGGREGATE_LABELS = { probability: '风险概率', chla: '叶绿素 a', biomass: '蓝藻生物量', density: '蓝藻密度' }
const aggregateRows = computed(() => {
  const metrics = props.aggregate?.metrics || {}
  return Object.entries(metrics).map(([key, m]) => ({
    key,
    label: AGGREGATE_LABELS[key] || key,
    text: `${fmtAgg(m.median)} [${fmtAgg(m.p25)}, ${fmtAgg(m.p75)}]${m.unit ? ` ${m.unit}` : ''}`
  }))
})
const aggregateBloomShare = computed(() => {
  const share = props.aggregate?.chla_bloom_share
  if (!share) return null
  return {
    threshold: share.threshold_ug_l,
    text: `${share.num}/${share.den} 站（${Math.round((share.share ?? 0) * 100)}%）`
  }
})

// 站点 vs 全湖中位：全湖聚合层随站点载荷附带（lake_aggregate），同一快照同源
const METRIC_UNIT = { probability: '', chla: 'μg/L', biomass: 'mg/L', density: '秩', area: 'km²' }
const stationVsLake = computed(() => {
  if (props.scope !== 'station') return null
  const agg = props.modelForecast?.lake_aggregate
  if (!agg?.metrics) return null
  const key = (props.modelForecast?.analysis_focus?.result_key) || FOCUS_KEY_BY_METRIC[props.metric] || 'probability'
  const stats = agg.metrics[key]
  const mine = ((props.modelForecast?.results || {})[key] || {}).value
  if (!stats || mine == null || stats.median == null) return null
  const delta = Number(mine) - Number(stats.median)
  const rel = Number(stats.median) !== 0 ? delta / Math.abs(Number(stats.median)) : null
  const dir = rel == null ? '不可比' : Math.abs(rel) < 0.02 ? '与全湖中位持平' : rel > 0 ? '高于全湖中位' : '低于全湖中位'
  const fmt = (v) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 3 })
  const unit = METRIC_UNIT[key] ? ` ${METRIC_UNIT[key]}` : props.modelForecast?.results?.[key]?.unit ? ` ${props.modelForecast.results[key].unit}` : ''
  return {
    text: `${fmt(mine)} vs ${fmt(stats.median)}${unit}（${delta >= 0 ? '+' : ''}${fmt(delta)}，${dir}）`
  }
})
const mechanismFactors = computed(() => {
  const factors = mechanismDrivers.value?.factors || []
  return factors.map((f) => {
    const has = f.value != null
    const pct = has ? Math.round(Number(f.value) * 1000) / 10 : 0
    const sourceRaw = f.source_value != null ? `${Number(f.source_value).toLocaleString('zh-CN', { maximumFractionDigits: 3 })} ${f.unit || ''}` : ''
    // 来源标注（审计口径）：优先后端逐项来源文本（本站实测·MEE 水温 / ERA5 网格 /
    // 气候态代理等），后端未给时回退到粗分类；禁止把代理值标成"本站实测"。
    let sourceLabel
    if (f.source) sourceLabel = f.source
    else if (f.key === 'flow' && f.source_value == null) sourceLabel = '缺少有效数据'
    else if (f.proxy) sourceLabel = '代理输入'
    else if (f.source_value != null) sourceLabel = '本站实测'
    else sourceLabel = '缺测'
    return {
      ...f,
      shortLabel: String(f.label || '').replace(/适合度|条件|输入/g, '') || f.label,
      stateOnly: Boolean(f.state_only),
      pct,
      // 适合度为 0-1 计算机理因子（与训练特征同式），不是观测百分比
      pctText: f.state_only ? (f.source_value != null ? '仅输入' : '不可用') : (has ? `适合度 ${pct}%` : '缺测'),
      color: !has ? 'rgba(127,147,168,0.4)' : f.value >= 0.6 ? '#5fd6a4' : f.value >= 0.35 ? '#f5b45d' : '#ef4444',
      sourceRaw,
      sourceLabel,
      // 逐站 / 全湖：结构化标志，后端未给时按 proxy 兜底（代理一律非逐站）
      stationResolution: f.station_resolution != null ? Boolean(f.station_resolution) : !f.proxy,
      saturated: Boolean(f.saturated),
      sourceText: [sourceRaw, sourceLabel].filter(Boolean).join(' · ')
    }
  })
})
// 来源分组说明：把"哪些逐站、哪些全湖"一次讲清，避免用户把全湖同值误读成站点数据没更新
const sourceGroups = computed(() => {
  const groups = mechanismDrivers.value?.source_groups
  if (!groups) return { note: '' }
  const labelOf = (key) => mechanismFactors.value.find((f) => f.key === key)?.shortLabel || key
  const per = (groups.per_station || []).map(labelOf).filter(Boolean)
  const wide = (groups.lake_wide || []).map(labelOf).filter(Boolean)
  const parts = []
  if (per.length) parts.push(`逐站：${per.join('、')}`)
  if (wide.length) parts.push(`全湖同值：${wide.join('、')}（单一气象网格，物理上无站间差异）`)
  return { note: parts.join('；') }
})
const driverGroups = computed(() => {
  const byKeys = (keys) => mechanismFactors.value.filter((f) => keys.includes(f.key))
  return [
    { key: 'environment', icon: '01', title: '环境条件', subtitle: '水温、气温与光照', factors: byKeys(['temperature', 'air_temperature', 'light']) },
    { key: 'nutrient', icon: '02', title: '营养盐供给', subtitle: '磷、氮与氨氮', factors: byKeys(['phosphorus', 'nitrogen', 'ammonia']) },
    { key: 'hydrodynamic', icon: '03', title: '水动力输运', subtitle: '流速与扩散条件', factors: byKeys(['flow']) }
  ].filter((group) => group.factors.length)
})
const mechanismLimiting = computed(() => {
  const key = mechanismDrivers.value?.limiting_factor
  if (!key) return null
  return mechanismFactors.value.find((f) => f.key === key) || null
})
const mechanismNet = computed(() => {
  const net = mechanismDrivers.value?.net_growth_rate_d
  const range = mechanismDrivers.value?.net_growth_range || [-0.16, 0.6]
  if (net == null) return null
  const span = range[1] - range[0]
  const zeroPct = ((0 - range[0]) / span) * 100
  const valuePct = ((Math.min(Math.max(net, range[0]), range[1]) - range[0]) / span) * 100
  const positive = net >= 0
  return {
    text: `${net >= 0 ? '+' : ''}${net.toFixed(3)} /d`,
    positive,
    style: positive
      ? { left: `${zeroPct}%`, width: `${Math.max(valuePct - zeroPct, 1)}%` }
      : { left: `${valuePct}%`, width: `${Math.max(zeroPct - valuePct, 1)}%` }
  }
})

// ---- 驱动因素：模型敏感性 ----
const modelExplanation = computed(() => focusResult.value?.explainability || null)
const modelFactors = computed(() => (modelExplanation.value?.factors || []).slice(0, 8))
const unavailableFactors = computed(() => modelExplanation.value?.unavailable_factors || [])
const maxContribution = computed(() =>
  modelFactors.value.reduce((m, f) => Math.max(m, f.contribution_percent), 0) || 1
)
function barWidth(v) {
  return `${Math.max(4, Math.round((v / maxContribution.value) * 100))}%`
}

// ---- 不确定性：split-conformal 预测区间刻度尺 ----
// 停用 is_calibrated_confidence_interval：该量在模型清单里恒为 true，
// 无法区分「区间结构自洽」与「校准证据充分」，旧代码据此判断会同时放过
// 退化区间（p05=p95）与 test_n=0 的空校准。现按新合同判定：
//   存在预测区间（is_prediction_interval !== false）即进入三层展示。
const v3Uncertainty = computed(() => {
  const u = modelUncertainty.value
  if (!u) return null
  return u.is_prediction_interval === false ? null : u
})
const modelUncertainty = computed(() => focusResult.value?.uncertainty || null)
const conformalPoint = computed(() => conformalValue(focusResult.value?.value))
const conformalProtocolNote = computed(() => {
  const protocol = v3Uncertainty.value?.training_protocol
  if (protocol === 'train_internal_time_block_cv_v1') {
    return '该模型为 T3/T4 补训（训练期内时间分块协议）：冻结验证/测试期无对应标签，区间校准与覆盖核算均非冻结划分口径。'
  }
  return ''
})
function conformalValue(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}
// 风险带标签 → 中文；带数值时按 μg/L 渲染
const RISK_BAND_TEXT = { none: '无风险', low: '低', medium: '中', high: '高', severe: '严重' }
const CALIBRATION_TEXT = {
  validated: '已核算', undercovered: '覆盖率未达标', no_test_evidence: '无测试证据',
  insufficient_test_evidence: '样本不足', unavailable: '不适用'
}
function bandText(band, numeric = false) {
  if (band == null) return '—'
  if (numeric) return conformalValue(band)
  return RISK_BAND_TEXT[band] || String(band)
}
function calibrationText(status) {
  return CALIBRATION_TEXT[status] || status || '—'
}
// 等级范围的承载对象：焦点任务自身带 band_range 时优先，否则取同一次输出的 risk_level 兄弟结果
const bandRangeUncertainty = computed(() => {
  if (v3Uncertainty.value?.band_range) return v3Uncertainty.value
  const sibling = props.modelForecast?.results?.risk_level?.uncertainty
  return sibling && sibling.band_range ? sibling : null
})
const bandRangeStatusText = computed(() => {
  const u = bandRangeUncertainty.value
  if (!u) return ''
  if (!u.structural_valid) return '区间无效'
  if (u.calibration_status !== 'validated') return '校准证据不足'
  return u.decision_usable ? '范围可用' : '谨慎参考'
})
// 源区间未达决策可用时，后端不给等级范围，只给原因（band_range_blocked）。
// 页面必须如实说明"为什么不给范围"，而不是留一个空态让人猜。
const bandRangeBlocked = computed(() => {
  const sibling = props.modelForecast?.results?.risk_level
  if (!sibling || sibling.uncertainty?.band_range) return null
  return sibling.band_range_blocked || null
})
const BLOCKED_REASON_TEXT = {
  source_interval_unavailable: '源区间不可用：叶绿素 a 在该时效没有预测区间',
  source_interval_structurally_invalid: '源区间结构不自洽（区间退化或点预测越界）',
  source_interval_band_mapping_failed: '源区间无法映射到冻结风险带'
}
function calibrationBlockText(blocked) {
  if (!blocked) return '—'
  const reason = blocked.reason || ''
  if (BLOCKED_REASON_TEXT[reason]) return BLOCKED_REASON_TEXT[reason]
  if (reason.startsWith('source_interval_')) {
    return `源区间校准证据不足：${calibrationText(reason.slice('source_interval_'.length))}`
  }
  return reason || '源区间未达决策可用'
}
// 状态判定严格镜像后端三层合同：①结构自洽 ②校准证据 ③决策可用。
// 顺序不可颠倒——结构不自洽时谈校准无意义；校准未 validated 时不得显示"区间可用"。
const UNCERTAINTY_STATUS_LABELS = {
  no_test_evidence: '冻结测试集无该任务标签，覆盖率无法核算，不构成校准证据。',
  insufficient_test_evidence: '冻结测试集样本过少，覆盖率不具统计意义，不构成校准证据。',
  undercovered: '冻结测试集经验覆盖率低于验收线，区间实际覆盖不足，不构成校准证据。',
  unavailable: '该任务未提供 conformal 预测区间。'
}
const uncertaintyStatus = computed(() => {
  const u = v3Uncertainty.value
  if (!u) return { key: 'none', title: '当前任务未提供预测区间', shortTitle: '无可用区间', detail: '不可用，不据此作决策。' }
  const structuralValid = Boolean(u.structural_valid)
  const calibStatus = u.calibration_status || 'unavailable'
  const testN = Number(u.test_n ?? u.coverage?.test_n ?? u.source_interval?.test_n ?? 0)
  // 等级范围（风险等级由叶绿素 a 区间映射）：没有数值区间可画，直接给范围结论。
  if (u.band_range) {
    if (!structuralValid) {
      return { key: 'invalid', shortTitle: '区间无效', title: '源区间结构不自洽，等级范围已停止解读',
        detail: u.decision_reason || '源区间结构层校验未通过，不据此作决策。' }
    }
    if (calibStatus !== 'validated') {
      return { key: 'insufficient', shortTitle: '校准证据不足', title: '等级范围可读，但源区间校准证据不足',
        detail: `${UNCERTAINTY_STATUS_LABELS[calibStatus] || '校准证据未通过'}（test_n=${testN}）` }
    }
    return {
      key: u.decision_usable ? 'usable' : 'watch',
      shortTitle: u.decision_usable ? '范围可用' : '谨慎参考',
      title: `等级范围：${bandText(u.p05_band)} — ${bandText(u.p95_band)}`,
      detail: u.note || '由叶绿素 a 预测区间按冻结风险带映射得到。'
    }
  }
  const p05 = Number(u.p05)
  const p95 = Number(u.p95)
  const point = Math.abs(Number(focusResult.value?.value))
  const width = p95 - p05
  // ① 结构层
  if (!structuralValid) {
    return {
      key: 'invalid',
      title: '预测区间结构不自洽，已停止按区间解读',
      shortTitle: '区间无效',
      detail: u.structural_reason || u.invalid_reason || '结构层校验未通过，不据此作决策。'
    }
  }
  // ② 校准证据层
  if (calibStatus !== 'validated') {
    return {
      key: 'insufficient',
      title: '区间结构自洽，但校准证据不足，不作决策依据',
      shortTitle: '校准证据不足',
      detail: `${UNCERTAINTY_STATUS_LABELS[calibStatus] || '校准证据未通过'}（test_n=${testN}）`
    }
  }
  if (Number.isFinite(width) && Math.abs(width) < 1e-12) {
    return { key: 'degenerate', title: '退化预测区间（无信息）', shortTitle: '区间退化', detail: 'P05=P95，区间退化；它没有表达可用的不确定性范围。' }
  }
  if (point > 0 && width / point > 1.5) {
    return { key: 'wide', title: '过宽预测区间（谨慎使用）', shortTitle: '范围偏宽', detail: `区间相对宽度 ${Math.round(width / point * 100)}%，当前不具备直接决策价值。` }
  }
  // ③ 决策层：结构 + 校准都过了才叫可用，仍以后端 decision_usable 为准
  if (u.decision_usable) {
    return { key: 'usable', title: '预测区间可用于决策参考', shortTitle: '区间可用', detail: '结构自洽、校准证据充分；经验覆盖率与样本量见上方明细。' }
  }
  return {
    key: 'watch',
    title: '预测区间结构自洽且校准已核算，但后端未判定为可决策',
    shortTitle: '谨慎参考',
    detail: u.decision_reason || '后端 decision_usable=false，仅作研判参考。'
  }
})
const intervalScale = computed(() => {
  const u = v3Uncertainty.value
  const focusKey = METRIC_KEYS[props.metric]
  const point = Number(focusResult.value?.value)
  // structuralValid 一并透出：调用方据此决定"画不画刻度尺"，
  // 避免把退化区间（p05=p95）画成看正常的区间条。
  const structuralValid = Boolean(u?.structural_valid)
  if (!u || u.p05 == null || u.p95 == null || !Number.isFinite(point)) {
    return { structuralValid: false }
  }
  const p05 = Number(u.p05)
  const p95 = Number(u.p95)
  const banded = focusKey === 'chla' || focusKey === 'probability'
  const domainMax = banded ? Math.max(50, p95 * 1.15) : Math.max(p95 * 1.08, point * 1.2, 0.0001)
  const x = (v) => Math.min(300, Math.max(0, (Math.min(Math.max(v, 0), domainMax) / domainMax) * 300))
  const segments = banded
    ? bandSegments(domainMax).map((seg) => ({
        x: (seg.left / 100) * 300, w: (seg.width / 100) * 300, color: seg.color
      }))
    : null
  const obs = focusKey === 'chla' ? Number(props.inputs?.chlaValue) : NaN
  return {
    structuralValid,
    segments,
    p05X: x(p05),
    p95X: Math.max(x(p95), x(p05) + 2),
    pointX: x(point),
    pointColor: banded ? bandColorOf(point) : '#38bdf8',
    pointText: conformalPoint.value,
    obsX: Number.isFinite(obs) ? x(obs) : null
  }
})

// ---- 不确定性：覆盖率环 + 9 任务区间矩阵 ----
// 覆盖率必须带证据才能"看起来达标"，且结构不自洽时覆盖率对本结果不适用：
// 那个数字描述的是校准器在留出集上的名义表现，不代表当前这条退化区间可用。
const coverageRing = computed(() => {
  const u = v3Uncertainty.value
  // 等级范围没有自己的覆盖率，继承源区间（叶绿素 a）的经验覆盖率——它才是被核算的那个量。
  const cov = u?.coverage?.empirical_coverage_test ?? u?.empirical_coverage ?? u?.source_interval?.empirical_coverage
  const target = u?.coverage?.target || 0.9
  const calibStatus = u?.calibration_status || 'unavailable'
  const structuralValid = Boolean(u?.structural_valid)
  if (cov == null) {
    return { dash: '0 ', color: 'rgba(127,147,168,0.5)', text: '未核算', note: '目标 90%' }
  }
  const pct = Math.round(Number(cov) * 1000) / 10
  const withinBand = Math.abs(Number(cov) - Number(target)) <= 0.1
  const applicable = structuralValid && calibStatus === 'validated'
  return {
    dash: `${(pct / 100) * 188.5} `,
    color: applicable && withinBand ? '#5fd6a4' : '#f5b45d',
    text: `${pct}%`,
    note: applicable
      ? `目标 ${Math.round(Number(target) * 100)}%`
      : (!structuralValid ? '区间结构不自洽，覆盖率不适用' : '校准证据不足，仅登记')
  }
})
const uncertaintyMatrix = computed(() => {
  const results = props.modelForecast?.results || {}
  return Object.entries(results).map(([key, item]) => {
    const u = item?.uncertainty
    const isPredictionInterval = Boolean(u) && u.is_prediction_interval !== false
    const isBandRange = isPredictionInterval && Boolean(u?.band_range)
    const hasInterval = isPredictionInterval && u.p05 != null && u.p95 != null
    const structuralValid = Boolean(u?.structural_valid)
    const calibStatus = u?.calibration_status || 'unavailable'
    const testN = Number(u?.test_n ?? u?.coverage?.test_n ?? u?.source_interval?.test_n ?? 0)
    const point = Number(item?.value)
    const width0 = hasInterval ? Number(u.p95) - Number(u.p05) : NaN
    let width = null
    if (hasInterval && point) {
      const rel = Math.min(width0 / Math.abs(point), 2)
      width = `${Math.max(rel * 50, 6)}%`
    }
    const LABELS = {
      bloom: '水华', chla: '叶绿素', area: '面积', coverage: '覆盖', density: '密度',
      biomass: '生物量', risk_level: '风险等级', probability: '风险概率', spatial: '空间'
    }
    // 与后端三层合同同序：结构 → 校准 → 决策。任一未过即不得标"可用"。
    // 等级范围（band_range）没有数值区间，按同一三层合同在其自身口径上判定。
    const statusText = isBandRange
      ? (!structuralValid ? '结构不自洽' : calibStatus !== 'validated' ? '校准证据不足' : (u.decision_usable ? '范围可用' : '参考'))
      : !hasInterval
        ? '无'
        : !structuralValid
          ? '结构不自洽'
          : calibStatus !== 'validated'
            ? `校准证据不足`
            : Math.abs(width0) < 1e-12
              ? '退化'
              : (point && width0 / Math.abs(point) > 1.5
                  ? '过宽'
                  : (u.decision_usable ? '可用' : '参考'))
    const title = isBandRange
      ? `${item.label}：等级范围 ${bandText(u.p05_band)} — ${bandText(u.p95_band)}（由叶绿素 a 区间映射）｜结构${structuralValid ? '自洽' : '不自洽'}｜校准 ${calibStatus}（test_n=${testN}）`
      : hasInterval
        ? `${item.label}：P05 ${Number(u.p05).toFixed(3)} ~ P95 ${Number(u.p95).toFixed(3)}｜结构${structuralValid ? '自洽' : '不自洽'}｜校准 ${calibStatus}（test_n=${testN}）｜决策可用 ${u.decision_usable ? '是' : '否'}（${item.value_origin || ''}）`
        : `${item.label}：未提供预测区间（${item.value_origin || 'not_applicable'}）`
    return {
      key,
      label: LABELS[key] || key,
      originKey: originKey(item),
      width,
      statusText,
      title
    }
  })
})

// ---- legacy V0.2 输入扰动情景分布 ----
const legacyPerturbation = computed(() => {
  const u = modelUncertainty.value
  return u && u.method === 'input_perturbation_scenario_distribution' ? u : null
})
function uncertaintyValue(value) {
  if (value == null) return '—'
  const unit = props.metric === 'risk' ? '%' : (focusResult.value?.unit || '')
  const numeric = Number(value) * (props.metric === 'risk' ? 100 : 1)
  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ''}`
}

// 切换对象时回到总览，避免停留在旧上下文的标签
watch(() => [props.scope, props.stationName], () => {
  activeTab.value = 'overview'
})

const STATION_KEY_VARS = [
  { code: 'chlorophyll_a', label: '叶绿素 a', unit: 'μg/L' },
  { code: 'water_temperature', label: '水温', unit: '℃' },
  { code: 'total_phosphorus', label: '总磷', unit: 'mg/L' },
  { code: 'total_nitrogen', label: '总氮', unit: 'mg/L' },
  { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L' },
  { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L' }
]

const stationKeyRows = computed(() => {
  if (!props.stationRows.length) return []
  const byCode = {}
  props.stationRows.forEach((row) => {
    const prev = byCode[row.variable_code]
    if (!prev || String(row.observed_at) > String(prev.observed_at)) byCode[row.variable_code] = row
  })
  return STATION_KEY_VARS.map(({ code, label, unit }) => {
    const row = byCode[code]
    const ok = row && row.observation_status === 'ok' && row.value != null
    return {
      label,
      text: ok ? `${row.value} ${unit}` : '缺测',
      miss: !ok
    }
  })
})

const stationObservedAt = computed(() => {
  const times = props.stationRows.map((r) => r.observed_at).filter(Boolean).sort()
  if (!times.length) return ''
  const m = String(times[times.length - 1]).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `观测 ${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ''
})
</script>

<style scoped>
.frp {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  min-width: 0;
}
.frp-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  align-self: flex-start;
}
.frp-tab {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 32px;
  padding: 4px 13px;
  border-radius: 999px;
  cursor: pointer;
}
.frp-tab.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.frp-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-body {
  display: grid;
  gap: 12px;
  align-content: start;
}

.frp-object {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
}
.frp-object-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.frp-object-tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-primary);
}
.frp-back {
  appearance: none;
  margin-left: auto;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  min-height: 28px;
  cursor: pointer;
}
.frp-back:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-stop-sub {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.frp-sub-h {
  margin: 2px 0 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}
.frp-sub-h span {
  font-size: 10px;
  font-weight: 500;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.frp-metric-tag {
  justify-self: start;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-primary);
  border: 1px solid color-mix(in srgb, var(--color-primary) 40%, transparent);
  border-radius: 999px;
  padding: 2px 9px;
}

/* ---------- 焦点 hero ---------- */
.frp-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel-soft);
}
.frp-hero-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 5px;
}
.frp-hero-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.frp-hero-value b {
  font-size: 32px;
  font-family: var(--font-mono);
  color: var(--text-primary);
  line-height: 1.1;
}
.frp-hero-unit {
  font-size: 13px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}
.frp-hero-label {
  font-size: 13px;
  color: var(--text-muted);
}
.frp-hero-scope {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.85;
}
/* 全湖聚合层未就绪（站点层补齐中）的如实等待态 */
.frp-agg-pending {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
  background: rgba(127, 147, 168, 0.06);
}
.frp-agg-pending b {
  font-size: 13px;
  color: var(--text-primary);
}
.frp-agg-pending span {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.frp-bandbar {
  display: grid;
  gap: 2px;
}
.frp-bandbar-track {
  position: relative;
  height: 8px;
  border-radius: 999px;
  background: rgba(127, 147, 168, 0.14);
  overflow: visible;
}
.frp-bandbar-seg {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 2px;
}
.frp-bandbar-line {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  border-radius: 999px;
  opacity: 0.85;
}
.frp-bandbar-marker {
  position: absolute;
  top: -3px;
  width: 4px;
  height: 14px;
  border-radius: 2px;
  background: var(--text-primary);
  box-shadow: 0 0 6px rgba(0, 0, 0, 0.45);
  transform: translateX(-2px);
}
.frp-bandbar-scale {
  position: relative;
  height: 12px;
  font-family: var(--font-mono);
  font-size: 8.5px;
  color: var(--text-muted);
}
.frp-bandbar-scale span {
  position: absolute;
  transform: translateX(-50%);
}
.frp-ring {
  display: grid;
  justify-items: center;
  gap: 3px;
  flex: 0 0 72px;
  min-width: 72px;
}
.frp-ring-label {
  font-size: 9.5px;
  color: var(--text-muted);
}
.frp-ring-text {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  fill: var(--text-primary);
}

.frp-gate {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.frp-gate-reason {
  flex: 1;
  min-width: 0;
}
.frp-gate-chip {
  flex-shrink: 0;
  font-family: inherit;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 1px 8px;
  margin-right: 2px;
}
.frp-gate-chip[data-gate='ok'] {
  color: #5fd6a4;
  border-color: color-mix(in srgb, #5fd6a4 55%, transparent);
}
.frp-gate-chip[data-gate='partial'] {
  color: #38bdf8;
  border-color: color-mix(in srgb, #38bdf8 55%, transparent);
}
.frp-gate-chip[data-gate='degraded'] {
  color: var(--risk-medium, #f5b45d);
  border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent);
}
.frp-gate-chip[data-gate='unavailable'] {
  color: var(--risk-critical, #ef4444);
  border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent);
}

/* ---------- 六宫格指标卡 ---------- */
.frp-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.frp-card {
  display: grid;
  gap: 4px;
  padding: 7px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  min-width: 0;
}
.frp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.frp-card-label {
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frp-card-value {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frp-card-bar {
  height: 4px;
  border-radius: 999px;
  background: rgba(127, 147, 168, 0.14);
  overflow: hidden;
}
.frp-card-bar--empty {
  opacity: 0.35;
}
.frp-card-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.frp-origin-chip {
  font-style: normal;
  font-family: inherit;
  font-size: 8.5px;
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 0 6px;
  white-space: nowrap;
}

/* ---------- 跨时效与门禁证据 ---------- */
.frp-horizon,
.frp-gate-table {
  display: grid;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-horizon {
  background: linear-gradient(145deg, color-mix(in srgb, #38bdf8 8%, var(--surface-panel-soft)), var(--surface-panel-soft));
}
.frp-quality-flag {
  justify-self: start;
  margin: -4px 0 0;
  padding: 3px 9px;
  border: 1px solid color-mix(in srgb, var(--risk-medium, #f5b45d) 48%, transparent);
  border-radius: 999px;
  color: var(--risk-medium, #f5b45d);
  font-size: 10px;
}
.frp-gate-table {
  min-width: 0;
  overflow-x: auto;
}
.frp-trend-axis { stroke: rgba(127, 147, 168, 0.35); stroke-width: 1; }
.frp-trend-split { stroke: var(--risk-medium, #f5b45d); stroke-width: 1; stroke-dasharray: 4 3; }
.frp-trend-band { fill: rgba(56, 189, 248, 0.14); stroke: rgba(56, 189, 248, 0.35); stroke-width: 1; }
.frp-trend-line { fill: none; stroke: var(--color-primary); stroke-width: 2; }
/* 情景推演段（T+30 起）：虚线 + 警示色，与短期真实预测在视觉上明确分口 */
.frp-trend-line--scenario {
  stroke: #e2a65a;
  stroke-dasharray: 5 4;
  stroke-opacity: 0.85;
}
.frp-trend-point { fill: #5fd6a4; stroke: var(--surface-panel); stroke-width: 1.5; }
.frp-trend-point[data-origin='cv'] { fill: #a78bfa; }
.frp-trend-point[data-origin='legacy'] { fill: var(--risk-medium, #f5b45d); }
.frp-trend-point[data-origin='derived'] { fill: #38bdf8; }
.frp-trend-point[data-origin='climatology'] { fill: #e2a65a; }
/* 合并后的短期段：一段同月区间，而不是四个看起来独立的预测点 */
.frp-trend-group {
  fill: color-mix(in srgb, #5fd6a4 22%, transparent);
  stroke: #5fd6a4;
  stroke-width: 1;
}
.frp-trend-label,
.frp-trend-caption { fill: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
.frp-trend-note { fill: var(--text-muted); font-family: var(--font-mono); font-size: 8px; }
.frp-trend-note[data-resolution='false'] { fill: #d9a55e; }
.frp-trend-note[data-resolution='true'] { fill: #57b98d; }
ul.frp-unc-note {
  margin: 2px 0 0;
  padding-left: 14px;
  list-style: disc;
}
ul.frp-unc-note li { margin: 1px 0; }
.frp-gate-row {
  display: grid;
  grid-template-columns: minmax(86px, 1.2fr) repeat(3, minmax(58px, 1fr)) minmax(78px, 1fr);
  gap: 6px;
  align-items: center;
  padding-top: 5px;
  border-top: 1px dashed var(--border-subtle);
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-secondary);
}
.frp-gate-row b { text-align: right; color: var(--text-primary); }
.frp-gate-row b[data-status='FAIL'] { color: var(--risk-critical, #ef4444); }
.frp-gate-row b[data-status='NA'] { color: var(--text-muted); }
.frp-origin-chip[data-origin='legacy'] {
  color: var(--risk-medium, #f5b45d);
}
.frp-origin-chip[data-origin='derived'] {
  color: #38bdf8;
}
.frp-origin-chip[data-origin='cv'] {
  color: #a78bfa;
}

/* ---------- 预测 vs 实测对照 ---------- */
.frp-compare {
  display: grid;
  gap: 5px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-compare-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.frp-compare-head b {
  font-size: 11.5px;
  color: var(--text-primary);
}
.frp-compare-head span {
  font-size: 9px;
  color: var(--text-muted);
}
.frp-compare-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.frp-compare-name {
  font-size: 10px;
  color: var(--text-muted);
}
.frp-compare-track {
  height: 8px;
  border-radius: 999px;
  background: rgba(127, 147, 168, 0.14);
  overflow: hidden;
}
.frp-compare-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.frp-compare-obs {
  background: #7dd3fc;
}
.frp-compare-val {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-primary);
  white-space: nowrap;
}

/* ---------- 追踪行 ---------- */
.frp-trace {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.frp-chip {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 2px 8px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.frp-chip--warn {
  color: var(--risk-critical, #ef4444);
  border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 45%, transparent);
}
.frp-details {
  width: 100%;
}
.frp-details summary {
  cursor: pointer;
  font-size: 10px;
  color: var(--color-primary);
  min-height: 24px;
  display: flex;
  align-items: center;
}
.frp-details summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-details[open] summary {
  margin-bottom: 4px;
}

.frp-kv {
  margin: 0;
  display: grid;
  gap: 4px;
}
.frp-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.frp-kv dt {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.frp-kv dd {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  text-align: right;
  word-break: break-all;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.frp-trend {
  font-style: normal;
  color: var(--risk-medium, #f5b45d);
}
.frp-miss {
  color: var(--text-muted) !important;
}

.frp-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}
.frp-warn {
  color: var(--text-secondary);
}

/* ---------- 站点环比变化摘要（实测参考） ---------- */
.frp-diff {
  display: grid;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
}
.frp-diff-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.frp-diff-head b {
  font-size: 12px;
  color: var(--text-primary);
}
.frp-diff-head span {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.frp-diff-counts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.frp-diff-stat {
  display: grid;
  gap: 1px;
  padding: 6px 8px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--text-muted) 7%, transparent);
  color: var(--text-muted);
  font-size: 10px;
}
.frp-diff-stat b { font-size: 17px; line-height: 1; color: var(--text-primary); }
.frp-diff-stat--up { background: rgba(239, 68, 68, 0.08); }
.frp-diff-stat--up b { color: #fb7185; }
.frp-diff-stat--down { background: rgba(95, 214, 164, 0.08); }
.frp-diff-stat--down b { color: #5fd6a4; }
.frp-diff-up { color: var(--risk-critical, #ef4444); }
.frp-diff-down { color: var(--risk-low, #5fd6a4); }
.frp-diff-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.frp-diff-list li {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
}
.frp-diff-list i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 5px currentColor;
}
.frp-diff-dot--up { background: #ef4444; color: #ef4444; }
.frp-diff-dot--down { background: #5fd6a4; color: #5fd6a4; }
.frp-diff-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.frp-diff-delta {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.frp-diff-chart { display: grid; gap: 7px; padding-top: 2px; }
.frp-diff-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 46px;
  gap: 8px;
  align-items: center;
}
.frp-diff-track {
  position: relative;
  display: block;
  height: 16px;
  border-bottom: 1px solid color-mix(in srgb, var(--text-muted) 25%, transparent);
}
.frp-diff-track i { position: absolute; display: block; }
.frp-diff-link { top: 7px; height: 2px; background: #7d93a8; }
.frp-diff-before,
.frp-diff-after { top: 4px; width: 8px; height: 8px; border-radius: 50%; transform: translateX(-4px); }
.frp-diff-before { border: 2px solid #7d93a8; background: var(--surface-panel); }
.frp-diff-after { background: #fb7185; box-shadow: 0 0 7px rgba(251,113,133,.5); }
.frp-diff-row[data-status='down'] .frp-diff-after { background: #5fd6a4; box-shadow: 0 0 7px rgba(95,214,164,.45); }
.frp-diff-row[data-status='flat'] .frp-diff-after { background: #7d93a8; box-shadow: none; }
.frp-diff-row[data-status='up'] .frp-diff-delta { color: #fb7185; }
.frp-diff-row[data-status='down'] .frp-diff-delta { color: #5fd6a4; }
.frp-empty {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

/* ---------- 驱动因素 ---------- */
.frp-method {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 7px 10px;
  background: var(--surface-panel-soft);
}
.frp-method b {
  font-size: 12px;
  color: var(--text-primary);
}
.frp-method span {
  font-size: 10px;
  line-height: 1.55;
  color: var(--text-muted);
}
.frp-driver-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 1px;
}
.frp-driver-head > div { display: grid; gap: 2px; }
.frp-driver-head b { font-size: 16px; color: var(--text-primary); }
.frp-driver-head span { font-size: 11px; color: var(--text-muted); }
.frp-driver-head strong {
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 4px 10px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.frp-driver-head strong[data-status='usable'] { color: #5fd6a4; }
.frp-driver-head strong[data-status='wide'],
.frp-driver-head strong[data-status='watch'],
.frp-driver-head strong[data-status='insufficient'] { color: var(--risk-medium, #f5b45d); }
.frp-driver-head strong[data-status='degenerate'],
.frp-driver-head strong[data-status='invalid'],
.frp-driver-head strong[data-status='none'] { color: #fb7185; }
.frp-driver-head--small b { font-size: 14px; }
.frp-driver-modules { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.frp-driver-module {
  display: grid;
  gap: 9px;
  padding: 11px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: linear-gradient(145deg, color-mix(in srgb, var(--color-primary) 8%, var(--surface-panel-soft)), var(--surface-panel-soft));
}
.frp-driver-module[data-group='hydrodynamic'] { grid-column: 1 / -1; }
.frp-driver-module header { display: flex; align-items: center; gap: 8px; }
.frp-driver-module header > i {
  display: grid; place-items: center; width: 28px; height: 28px; border-radius: 9px;
  background: color-mix(in srgb, var(--color-primary) 18%, transparent); color: var(--color-primary);
  font: 700 10px/1 var(--font-mono); font-style: normal;
}
.frp-driver-module header > div { display: grid; gap: 1px; }
.frp-driver-module header b { font-size: 13px; color: var(--text-primary); }
.frp-driver-module header span { font-size: 10px; color: var(--text-muted); }
.frp-factor-row { display: grid; gap: 4px; }
.frp-factor-label { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.frp-factor-label span { font-size: 12px; color: var(--text-secondary); }
.frp-factor-label b { font: 700 13px/1 var(--font-mono); color: var(--text-primary); }
.frp-factor-row > small { font: 9px/1.2 var(--font-mono); color: var(--text-muted); }
/* 逐站 / 全湖 来源徽标：让"这个值是不是本站的"一眼可判，不必读来源长句 */
.frp-factor-row > small em {
  font-style: normal;
  margin-right: 4px;
  padding: 0 4px;
  border-radius: 3px;
  border: 1px solid var(--border-subtle);
}
.frp-factor-row > small em[data-resolution='station'] { color: #5fd6a4; border-color: rgba(95,214,164,0.4); }
.frp-factor-row > small em[data-resolution='lake'] { color: #f5b45d; border-color: rgba(245,180,93,0.4); }
.frp-ai-module { display: grid; gap: 9px; padding: 11px 12px; border: 1px solid var(--border-subtle); border-radius: 12px; }
.frp-ai-empty { padding: 16px; border-radius: 9px; text-align: center; background: var(--surface-panel-soft); color: var(--text-muted); font-size: 12px; }

.frp-factors,
.frp-bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.frp-factors li,
.frp-bars li {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.frp-bar-label {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: grid;
  gap: 1px;
}
.frp-factor-proxy {
  font-size: 8.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.frp-bar-track {
  height: 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text-muted, #7d93a8) 16%, transparent);
  overflow: hidden;
}
.frp-factor-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.frp-bar-warm {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(to right, color-mix(in srgb, #f5b45d 70%, transparent), #ef4444);
}
.frp-bar-value {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-primary);
  white-space: nowrap;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.frp-bar-value small {
  color: var(--risk-critical, #ef4444);
  font-weight: 700;
}

.frp-limit {
  display: grid;
  gap: 2px;
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 40%, transparent);
  background: color-mix(in srgb, var(--risk-critical, #ef4444) 7%, transparent);
  border-radius: 10px;
  padding: 7px 10px;
}
.frp-limit b {
  font-size: 11.5px;
  color: var(--risk-critical, #ef4444);
}
.frp-limit span {
  font-size: 10px;
  color: var(--text-secondary);
  line-height: 1.55;
}

.frp-net {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-net-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.frp-net-head b {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}
.frp-net-up { color: #5fd6a4; font-size: 10.5px; }
.frp-net-down { color: var(--risk-critical, #ef4444); font-size: 10.5px; }
.frp-net-track {
  position: relative;
  height: 10px;
  border-radius: 999px;
  background: rgba(127, 147, 168, 0.14);
}
.frp-net-zero {
  position: absolute;
  left: 21%;
  top: -2px;
  width: 2px;
  height: 14px;
  background: var(--text-muted);
}
.frp-net-fill {
  position: absolute;
  top: 1px;
  height: 8px;
  border-radius: 999px;
}
.frp-net-fill--up { background: #5fd6a4; }
.frp-net-fill--down { background: var(--risk-critical, #ef4444); }
.frp-net-scale {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 8.5px;
  color: var(--text-muted);
}

.frp-line-note {
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-muted);
  border-left: 2px solid var(--border-subtle);
  padding: 2px 0 2px 8px;
}

.frp-neutral {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.frp-neutral li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 10.5px;
  line-height: 1.5;
}
.frp-neutral b {
  font-weight: 600;
  color: var(--color-primary);
  white-space: nowrap;
  font-family: var(--font-mono);
}
.frp-neutral span {
  color: var(--text-muted);
}

/* ---------- 不确定性 ---------- */
.frp-scale {
  padding: 10px 10px 4px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-scale-text {
  font-family: var(--font-mono);
  font-size: 11px;
  fill: var(--text-primary);
}
.frp-scale-text--dim {
  fill: var(--text-muted);
}

.frp-unc-grid {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}
.frp-unc-stats {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 7px;
}
.frp-unc-stats > div { display: grid; gap: 3px; padding: 9px 10px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-panel-soft); }
.frp-unc-stats > div.active { border-color: color-mix(in srgb, #38bdf8 60%, transparent); background: color-mix(in srgb, #38bdf8 8%, var(--surface-panel-soft)); }
.frp-unc-stats dt { font-size: 10px; color: var(--text-muted); }
.frp-unc-stats dd { margin: 0; font: 700 15px/1.2 var(--font-mono); color: var(--text-primary); }
.frp-ring-card {
  display: grid;
  justify-items: center;
  gap: 4px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-ring-meta {
  display: grid;
  gap: 1px;
  justify-items: center;
}
.frp-ring-meta b {
  font-size: 12px;
  color: var(--text-primary);
}
.frp-ring-meta span {
  font-size: 8.5px;
  color: var(--text-muted);
}
.frp-matrix {
  display: grid;
  gap: 5px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  min-width: 0;
}
.frp-matrix-title {
  font-size: 13px;
  color: var(--text-primary);
}
.frp-matrix-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
}
.frp-matrix-cell {
  position: relative;
  overflow: hidden;
  font-size: 11px;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  padding: 3px 6px 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frp-matrix-cell small {
  display: block;
  margin-top: 2px;
  font-size: 9.5px;
  color: currentColor;
  opacity: 0.85;
}
.frp-matrix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 8.5px;
  color: var(--text-muted);
}
.frp-matrix-cell[data-origin='real'] {
  border-color: color-mix(in srgb, #5fd6a4 45%, transparent);
  color: #5fd6a4;
}
.frp-matrix-cell[data-origin='cv'] {
  border-color: color-mix(in srgb, #a78bfa 45%, transparent);
  color: #a78bfa;
}
.frp-matrix-cell[data-origin='derived'] {
  border-color: color-mix(in srgb, #38bdf8 45%, transparent);
  color: #38bdf8;
}
.frp-matrix-cell[data-origin='legacy'] {
  border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 45%, transparent);
  color: var(--risk-medium, #f5b45d);
}
.frp-matrix-cell[data-origin='none'] {
  opacity: 0.5;
}
.frp-matrix-width {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  background: currentColor;
  opacity: 0.6;
}

.frp-blocked {
  display: grid;
  gap: 3px;
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent);
  border-radius: 10px;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 5%, transparent);
}
.frp-blocked > b {
  font-size: 12px;
  color: var(--risk-medium, #f5b45d);
}
.frp-blocked > span {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* 区间三层校验的理由文本：把"为什么不能用"直接写在状态芯片下方，
   避免只给一个"区间无效"结论而让人猜原因。 */
.frp-unc-note {
  margin: 0 0 2px;
  font-size: 11px;
  line-height: 1.65;
  color: var(--text-muted, #7d93a8);
}

/* 源区间未达决策可用：整块以警示边框呈现，明确"不给范围"是判定结果而非渲染缺陷。 */
[data-role='band-range-blocked'] {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  margin: 4px 0 8px;
  border: 1px solid color-mix(in srgb, #fb7185 38%, transparent);
  border-left-width: 3px;
  border-radius: 10px;
  background: color-mix(in srgb, #fb7185 6%, var(--surface-panel-soft));
}
[data-role='band-range-blocked'] .frp-driver-head { margin: 0; }
[data-role='band-range-blocked-reason'] { font-family: var(--font-mono); }

.frp-inline-btn {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 4px 12px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.frp-inline-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

@media (max-width: 759px) {
  .frp-tab {
    min-height: 44px;
  }
  .frp-gate-row {
    grid-template-columns: minmax(80px, 1fr) repeat(2, minmax(64px, 1fr));
  }
  .frp-gate-row span:nth-of-type(4) { display: none; }
}


/* 全湖聚合层（79 站分布摘要） */
.frp-agg { display: flex; flex-direction: column; gap: 6px; }
.frp-agg-note { margin: 0; font-size: 10px; color: var(--text-secondary, #7d93a8); }
</style>
