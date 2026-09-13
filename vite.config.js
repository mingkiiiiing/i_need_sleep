import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端代理地址：默认 8000（标准部署口径，与 start-a23-dev.ps1 的 -BackendPort 默认值一致）。
// 8000 被其他项目占用时（本机当前开发机即如此），后端改跑 8010，启动时设
// BACKEND_ORIGIN=http://127.0.0.1:8010 覆盖（start-a23-dev.ps1 -BackendPort 8010 会自动设置该变量）。
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
