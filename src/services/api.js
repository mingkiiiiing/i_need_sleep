// 后端接口适配层。当后端就绪时，把 fetch 调用改为真实 HTTP 请求，
// 把 mock.js 中的模拟数据替换为接口响应即可。
//
// 调用约定：所有方法返回 Promise<...>，调用方应使用 await。
// 出错约定：网络错误抛出异常，由上层决定是否回退到 mock。

import * as mock from './mock.js'

const USE_MOCK = true

function wrap(method) {
  if (USE_MOCK) {
    return mock[method.name] || method
  }
  return method
}

export async function getTimeStages() {
  return wrap(mock.fetchTimeStages)()
}

export async function getPoints() {
  return wrap(mock.fetchPoints)()
}

export async function getPointDetail(id) {
  return wrap(mock.fetchPointDetail)(id)
}

export async function getHeatField() {
  return wrap(mock.fetchHeatField)()
}

export async function getEvents() {
  return wrap(mock.fetchEvents)()
}

export async function getRegionSummary() {
  return wrap(mock.fetchRegionSummary)()
}