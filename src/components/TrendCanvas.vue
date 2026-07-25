<template>
  <canvas ref="canvasRef" width="420" height="180"></canvas>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  values: { type: Array, required: true }
})

const canvasRef = ref(null)

function render() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width
  const h = canvas.height
  const values = props.values
  ctx.clearRect(0, 0, w, h)
  ctx.strokeStyle = 'rgba(16,37,29,0.08)'
  ctx.lineWidth = 1
  for (let i = 0; i < 4; i += 1) {
    const y = 20 + ((h - 38) / 4) * i
    ctx.beginPath()
    ctx.moveTo(18, y)
    ctx.lineTo(w - 18, y)
    ctx.stroke()
  }
  const startX = 24
  const endX = w - 24
  const stepX = (endX - startX) / (values.length - 1)
  const min = Math.min(...values) - 6
  const max = Math.max(...values) + 6
  ctx.beginPath()
  values.forEach((value, index) => {
    const x = startX + stepX * index
    const y = h - 24 - ((value - min) / (max - min)) * (h - 54)
    if (index === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  const gradient = ctx.createLinearGradient(0, 0, w, 0)
  gradient.addColorStop(0, '#78d9c3')
  gradient.addColorStop(0.5, '#84c98f')
  gradient.addColorStop(1, '#e86e58')
  ctx.strokeStyle = gradient
  ctx.lineWidth = 4
  ctx.stroke()
}

onMounted(render)
watch(() => props.values, render)
</script>
