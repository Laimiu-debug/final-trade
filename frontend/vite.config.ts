import path from 'node:path'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

function patchAntdEllipsisPlugin(): Plugin {
  const patchPath = path.resolve(__dirname, 'src/patches/antdEllipsisMeasure.tsx')
  const importerPattern = /\/node_modules\/antd\/(es|lib)\/typography\/Base\/index(?:\.js|\.mjs)?$/

  const normalize = (value: string) => value.replace(/\\/g, '/').split('?')[0]

  return {
    name: 'patch-antd-ellipsis-measure',
    enforce: 'pre',
    resolveId(source, importer) {
      if (!importer) return null
      if (source !== './Ellipsis' && source !== './Ellipsis.js') return null
      const normalizedImporter = normalize(importer)
      if (importerPattern.test(normalizedImporter)) {
        return patchPath
      }
      return null
    },
  }
}

function patchAntdEllipsisOptimizePlugin() {
  const patchPath = path.resolve(__dirname, 'src/patches/antdEllipsisMeasure.tsx').replace(/\\/g, '/')
  const importerPattern = /\/node_modules\/antd\/(es|lib)\/typography\/Base\/index(?:\.js|\.mjs)?$/

  return {
    name: 'patch-antd-ellipsis-measure-optimize',
    setup(build: any) {
      build.onResolve({ filter: /^\.\/Ellipsis(?:\.js)?$/ }, (args: { importer?: string }) => {
        const importer = (args.importer ?? '').replace(/\\/g, '/')
        if (importerPattern.test(importer)) {
          return { path: patchPath }
        }
        return null
      })
    },
  } as any
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [patchAntdEllipsisPlugin(), react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    optimizeDeps: {
      esbuildOptions: {
        plugins: [patchAntdEllipsisOptimizePlugin()],
      },
    },
    server: {
      port: 4173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
