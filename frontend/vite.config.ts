import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// Port 3000 with strictPort is deliberate, not a preference.
// The backend's CORS_ALLOWED_ORIGINS defaults to http://localhost:3000 and
// http://127.0.0.1:3000, CORS_ALLOW_ALL_ORIGINS is false, and
// CORS_ALLOW_CREDENTIALS is false. A fallback port would produce an origin the
// backend refuses, so failing to start is better than starting unusable.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 3000, strictPort: true, host: 'localhost' },
  preview: { port: 3000, strictPort: true },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
