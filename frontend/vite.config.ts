import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Where the FastAPI backend is listening. Override with BACKEND_URL when it
// runs somewhere other than the default uvicorn port.
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

// Port 5173 is not arbitrary: it is what backend/app/main.py allows in its CORS
// origins, so a direct fetch works even if the proxy below is bypassed.
const PORT = parseInt(process.env.PORT || '5173')

// Proxying /api keeps the browser on one origin, so there is no preflight and
// no backend host baked into the production bundle.
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
