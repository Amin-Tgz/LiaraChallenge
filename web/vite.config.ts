import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The bundle is served from the API origin in every environment, so dev proxies
// `/api` and `/health` to the local API rather than configuring CORS.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: false },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
