import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Backend address for the dev proxy below (override with BACKEND_URL).
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

// 5173 matches the CORS origins allowed in backend/app/main.py.
const PORT = parseInt(process.env.PORT || '5173')

// Forward /api requests to the backend, so the browser only talks to one
// server (no CORS issues, no backend URL hardcoded in the build).
const proxy = {
  '/api': { target: BACKEND_URL, changeOrigin: true },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: { port: PORT, strictPort: true, proxy },
  preview: { port: PORT, strictPort: true, proxy },
})
