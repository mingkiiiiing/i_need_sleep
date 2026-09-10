import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端地址可用环境变量覆盖（如 8000 被其他项目占用时：BACKEND_ORIGIN=http://127.0.0.1:8001）
const backendOrigin = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000'

const apiProxy = {
  '/api': {
    target: backendOrigin,
    changeOrigin: true
  },
  '/rs': {
    target: backendOrigin,
    changeOrigin: true
  }
}

export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: apiProxy
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    proxy: apiProxy
  }
})
