import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 与 server.py 默认 OCR_CHAIN_PORT=8001 保持一致；可在 web-ui/.env.development 中设置 VITE_API_PORT
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiPort = env.VITE_API_PORT || '8001'
  const apiTarget = `http://127.0.0.1:${apiPort}`

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (path) => path,
        },
      },
    },
  }
})
