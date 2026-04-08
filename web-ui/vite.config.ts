import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 与 server.py 默认 OCR_CHAIN_PORT=1129 保持一致；可在 web-ui/.env.development 中设置 VITE_API_PORT
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiPort = env.VITE_API_PORT || '1129'
  const apiTarget = `http://127.0.0.1:${apiPort}`

  // exe 模式下 base 为 /web-ui/，与 server.py 中的挂载路径保持一致
  // 开发模式下 base 为 /（利用 Vite 开发服务器的绝对路径）
  const isProd = mode === 'production'
  const base = isProd ? '/web-ui/' : '/'

  return {
    plugins: [react()],
    base,
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
