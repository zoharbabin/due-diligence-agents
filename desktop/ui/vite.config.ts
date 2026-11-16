/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Browser dev mode: `dd-agents serve` prints a token and port. Run
//   DD_DEV_API=http://127.0.0.1:PORT npm run dev
// then open http://localhost:5173/?token=TOKEN. The proxy keeps the UI same-origin,
// so the API needs no CORS.
const target = process.env.DD_DEV_API ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (req) => req.setHeader('origin', target))
        },
      },
    },
  },
  build: { sourcemap: false, target: 'es2022' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
