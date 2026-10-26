import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API (server/api.py) runs on :8000; proxy so the dev server and the built app use the same relative URLs.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
