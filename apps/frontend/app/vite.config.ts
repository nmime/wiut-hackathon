import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: {
      '/api': process.env.VITE_API_PROXY_URL ?? 'http://127.0.0.1:3000',
    },
  },
  preview: {
    proxy: {
      '/api': process.env.VITE_API_PROXY_URL ?? 'http://127.0.0.1:3000',
    },
  },
});
