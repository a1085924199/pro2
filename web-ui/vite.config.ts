import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 将前端所有 /api/* 请求代理到 Python 后端
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path, // 保留 /api 前缀（server.py 路由已含 /api）
      },
    },
  },
})
