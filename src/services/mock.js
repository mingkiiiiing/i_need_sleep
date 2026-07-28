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




export function fetchPointsSync() {


  return { pointData, pointPositions }


}




export function fetchEventsSync() {


  return eventStream


}




export function fetchHeatFieldSync() {


  return heatGrid


}




export function fetchRegionSummarySync() {


  return regionSummary


}




export function fetchTimeStagesSync() {


  return timeStages


}

