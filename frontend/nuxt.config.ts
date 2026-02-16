// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({

  modules: [
    '@nuxt/eslint',
    '@nuxt/ui'
  ],

  devServer: {
    host: '127.0.0.1'
  },

  devtools: {
    enabled: true
  },

  css: ['~/assets/css/main.css'],

  vite: {
    server: {
      allowedHosts: ['.trycloudflare.com']
    }
  },

  compatibilityDate: '2025-01-15',

  nitro: {
    devProxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/runs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/logs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  }
})
