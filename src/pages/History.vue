<template>
  <main class="shell">
    <section class="page-hero">
      <p class="eyebrow">Cockpit · History</p>
      <h1>历史轨迹</h1>
      <p>本页单独承载时间轴、事件回溯和趋势变化，避免和地图点位、风险热区混在一页里。</p>
      <div class="actions">
        <RouterLink class="button primary" to="/stations">返回监测站页</RouterLink>
        <RouterLink class="button secondary" to="/cockpit">返回驾驶舱总览</RouterLink>
      </div>
    </section>
    <section class="history-list">
      <article><strong>07-16</strong><p>系统开始记录近期蓝藻风险波动。</p></article>
      <article><strong>07-20</strong><p>热点区风险抬升，进入重点关注阶段。</p></article>
      <article><strong>07-23</strong><p>西北热点区进入橙色预警窗口。</p></article>
      <article><strong>07-30</strong><p>用于展示未来趋势回放和情景推演。</p></article>
    </section>
  </main>
</template>
