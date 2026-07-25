<template>
  <aside class="detail-panel panel">
    <div class="panel-head detail-head">
      <div>
        <p class="panel-kicker">Point Detail</p>
        <h2>{{ point.name }}</h2>
      </div>
      <span class="risk-badge" :class="point.riskClass">{{ point.risk }}</span>
    </div>

    <p class="detail-summary">{{ point.summary }}</p>

    <div class="detail-grid metrics-grid">
      <article><span>藻密度</span><strong>{{ point.metrics.density }}</strong></article>
      <article><span>叶绿素 a</span><strong>{{ point.metrics.chla }}</strong></article>
      <article><span>总磷</span><strong>{{ point.metrics.phosphorus }}</strong></article>
      <article><span>水温</span><strong>{{ point.metrics.temp }}</strong></article>
    </div>

    <section class="detail-section">
      <div class="section-line">
        <h3>点位预测</h3>
        <span>{{ point.forecast.window[stage] }}</span>
      </div>
      <div class="forecast-card">
        <strong>{{ point.forecast.title[stage] }}</strong>
        <p>{{ point.forecast.text[stage] }}</p>
      </div>
    </section>

    <section class="detail-section">
      <div class="section-line">
        <h3>驱动因子</h3>
        <span>可解释分析</span>
      </div>
      <div class="factor-list">
        <div v-for="[name, value] in point.factors" :key="name" class="factor-row">
          <div class="factor-meta"><span>{{ name }}</span><strong>{{ value }}</strong></div>
          <div class="factor-track"><div class="factor-fill" :style="{ width: `${value}%` }"></div></div>
        </div>
      </div>
    </section>

    <section class="detail-section">
      <div class="section-line">
        <h3>点位事件流</h3>
        <span>监测与应急</span>
      </div>
      <div class="timeline-list">
        <div v-for="[time, title, text] in point.timeline" :key="`${time}-${title}`" class="timeline-item">
          <div class="timeline-time">{{ time }}</div>
          <div>
            <strong>{{ title }}</strong>
            <p>{{ text }}</p>
          </div>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
defineProps({
  point: { type: Object, required: true },
  stage: { type: Number, default: 1 }
})
</script>
