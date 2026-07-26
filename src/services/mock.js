// Mock 服务。当后端就绪后，把每个函数体的实现替换为 fetch 调用即可。
// 现阶段所有方法都返回本地 mock，对外保持一致。

import {
  pointData,
  pointPositions,
  timeStages,
  eventStream,
  heatGrid,
  regionSummary
} from '../data/points.js'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function fetchTimeStages() {
  await delay(40)
  return timeStages
}

export async function fetchPoints() {
  await delay(60)
  return { pointData, pointPositions }
}

export async function fetchPointDetail(id) {
  await delay(60)
  return pointData[id]
}

export async function fetchHeatField() {
  await delay(60)
  return heatGrid
}

export async function fetchEvents() {
  await delay(60)
  return eventStream
}

export async function fetchRegionSummary() {
  await delay(40)
  return regionSummary
}