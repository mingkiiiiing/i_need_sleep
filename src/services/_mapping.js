// 后端 -> 前端数据适配层
// 站点 ID 映射：后端 8 个站点中，前端只使用前 6 个太湖点位
const SITE_ID_MAP = {
  S001: 'northwest_hotspot',
  S002: 'central_lake',
  S003: 'river_inlet',
  S004: 'southeast_station',
  S005: 'water_intake',
  S006: 'south_channel'
}

const SHORT_LABEL_MAP = {
  northwest_hotspot: 'NW-01',
  central_lake: 'CN-02',
  river_inlet: 'RI-03',
  southeast_station: 'SE-04',
  water_intake: 'WI-05',
  south_channel: 'SC-06'
}

const SEVERITY_TO_CLASS = { high: 'high', medium: 'mid', low: 'low' }
const RISK_DISPLAY = { high: '红色预警', medium: '黄色关注', low: '绿色稳定' }
const SEVERITY_TO_FRONT = { high: 'high', medium: 'mid', low: 'low' }

export { SITE_ID_MAP, SHORT_LABEL_MAP, SEVERITY_TO_CLASS, SEVERITY_TO_FRONT, RISK_DISPLAY }
