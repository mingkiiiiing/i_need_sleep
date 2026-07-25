<template>
  <main class="shell">
    <section class="page-hero">
      <p class="eyebrow">Cockpit · Risk Heatmap</p>
      <h1>风险热区</h1>
      <p>本页单独展示风险分区和热点扩张情况，不再和监测站详情挤在同一个页面中。</p>
      <div class="actions">
        <RouterLink class="button primary" to="/history">下一页：历史轨迹</RouterLink>
        <RouterLink class="button secondary" to="/cockpit">返回驾驶舱总览</RouterLink>
      </div>
    </section>
    <section class="heatmap-stage">
      <div class="water-grid"></div>
      <div class="heat-overlay heat-overlay-a"></div>
      <div class="heat-overlay heat-overlay-b"></div>
      <div class="heat-legend"><span class="legend-dot high"></span>高风险热区 <span class="legend-dot mid"></span>关注区</div>
    </section>
  </main>
</template>
