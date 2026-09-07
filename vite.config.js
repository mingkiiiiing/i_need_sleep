import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxy = {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true
  },
  '/rs': {
    target: 'http://127.0.0.1:8000',
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
