import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '')
    const flaskOrigin = env.VITE_FLASK_ORIGIN || 'http://127.0.0.1:8000'
    const allowedHosts = (env.VITE_ALLOWED_HOSTS || '')
        .split(',')
        .map((host) => host.trim())
        .filter(Boolean)

    return {
        plugins: [
            react(),
        ],
        build: {
            rollupOptions: {
                input: {
                    index: resolve(__dirname, 'index.html'),
                    bookshelf: resolve(__dirname, 'bookshelf.html'),
                },
            },
        },
        server: {
            host: '127.0.0.1',
            allowedHosts,
            proxy: {
                '^/books/': {
                    target: flaskOrigin,
                    changeOrigin: true,
                },
                '/api': {
                    target: flaskOrigin,
                    changeOrigin: true,
                }
            }
        },
    }
})
