import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the API runs on :8000; the proxy keeps everything same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000', changeOrigin: true } },
  },
  build: { target: 'es2022', sourcemap: false },
});
