import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },

  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@/assets/styles/variables.scss" as *;`,
      },
    },
  },

  server: {
    port: 5173,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },

  build: {
    rolldownOptions: {
      onLog(level, log, defaultHandler) {
        if (
          log.code === 'INVALID_ANNOTATION' &&
          typeof log.loc?.file === 'string' &&
          log.loc.file.includes('@vueuse/core')
        ) {
          return
        }

        defaultHandler(level, log)
      },
      output: {
        codeSplitting: {
          maxSize: 450000,
          groups: [
            {
              name: 'vendor-vue',
              test: /[\\/]node_modules[\\/](vue|vue-router|pinia)[\\/]/,
            },
            {
              name: 'vendor-element',
              test: /[\\/]node_modules[\\/](element-plus|@element-plus|@vueuse)[\\/]/,
            },
            {
              name: 'vendor-utils',
              test: /[\\/]node_modules[\\/](axios|markdown-it)[\\/]/,
            },
          ],
        },
      },
    },
  },

  test: {
    environment: 'happy-dom',
    testTimeout: 10000,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.{test,spec}.{js,ts}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
    },
  },
})
