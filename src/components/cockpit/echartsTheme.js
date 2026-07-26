// 暗色主题 ECharts 配置。集中在这里，便于统一调整。

export const echartsBase = {
  textStyle: {
    color: '#a9bcd4',
    fontFamily: 'Microsoft YaHei, PingFang SC, sans-serif'
  },
  color: ['#22d3c5', '#f4c062', '#ff7b6b', '#a78bfa', '#6ee7b7']
}

export const tooltipBase = {
  backgroundColor: 'rgba(8,16,28,0.92)',
  borderColor: 'rgba(34,211,197,0.4)',
  borderWidth: 1,
  textStyle: { color: '#e6f1ff', fontSize: 12 },
  extraCssText: 'backdrop-filter: blur(8px); box-shadow: 0 12px 28px rgba(0,0,0,0.45);'
}

export const gridBase = (extra = {}) => ({
  left: 40,
  right: 16,
  top: 24,
  bottom: 28,
  containLabel: true,
  ...extra
})

export const axisLine = {
  lineStyle: { color: 'rgba(120,200,220,0.18)' }
}
export const splitLine = {
  lineStyle: { color: 'rgba(120,200,220,0.08)' }
}
export const axisLabel = {
  color: '#6f8aa3',
  fontSize: 11
}