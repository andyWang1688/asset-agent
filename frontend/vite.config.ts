/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  css: {
    // 用 Lightning CSS 按 targets 降级现代 CSS 特性：
    // oklch()/color-mix() 编译为静态 rgb 值，CSS 嵌套展开，
    // 让旧版 Safari/Chrome 也能正确显示设计稿的 oklch 色板。
    transformer: 'lightningcss',
    lightningcss: {
      targets: {
        safari: (15 << 16) | (4 << 8), // Safari 15.4
        ios_saf: (15 << 16) | (4 << 8),
        chrome: 100 << 16,
        edge: 100 << 16,
        firefox: 100 << 16,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
