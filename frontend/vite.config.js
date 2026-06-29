import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Разработка: Vite-дев-сервер (5173) с HMR; запросы к /api проксируются на Django
// (localhost:8000) — поэтому нет проблем с CORS и можно слать Bearer-токен.
// Продакшен: `npm run build` собирает статику в dist/, которую отдаёт Django на /.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
