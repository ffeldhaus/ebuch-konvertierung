import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [tailwindcss()],
  root: './frontend',
  server: {
    port: 3000,
    watch: {
      ignored: ['**/assets/**']
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  }
});
