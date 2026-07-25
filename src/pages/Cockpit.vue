<template>
  <main class="shell">
    <section class="page-hero">
      <p class="eyebrow">Cockpit</p>
      <h1>驾驶舱总览</h1>
      <p>这里不再把所有 tab 放在一页，而是把原来的几个 tab 变成三个独立页面。可以从这里分别进入监测站、风险热区和历史轨迹页面。</p>
      <div class="actions">
        <RouterLink class="button primary" to="/stations">进入监测站页</RouterLink>
        <RouterLink class="button secondary" to="/">返回首页</RouterLink>
      </div>
    </section>

    <section class="home-grid">
      <RouterLink class="nav-card" to="/stations">
        <small>Tab 01</small>
        <strong>监测站</strong>
        <p>单独展示地图点位、点击展开详情和点位监测数据。</p>
      </RouterLink>
      <RouterLink class="nav-card" to="/heatmap">
        <small>Tab 02</small>
        <strong>风险热区</strong>
        <p>单独展示风险分区、热点扩张和预警等级。</p>
      </RouterLink>
      <RouterLink class="nav-card" to="/history">
        <small>Tab 03</small>
        <strong>历史轨迹</strong>
        <p>单独展示时间推演、趋势变化和事件回溯。</p>
      </RouterLink>
    </section>
  </main>
</template>
