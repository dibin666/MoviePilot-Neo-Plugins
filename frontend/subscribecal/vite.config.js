import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

// 插件组件间共享的代码块（非依赖、非本地预览入口）统一加上 __federation_ 前缀，
// 以便 finalize-dist.sh 白名单保留这些文件
function isPluginChunk(chunk) {
  const ids = chunk.moduleIds || []
  if (!ids.length || /^(__federation_|_plugin-vue_)/.test(chunk.name || '')) return false
  if (ids.some(id => id.includes('node_modules') || /\/src\/(App\.vue|main\.js)/.test(id))) return false
  return ids.some(id => id.includes('/src/'))
}

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'SubscribeCal',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
        './Dashboard': './src/components/Dashboard.vue',
        './AppPage': './src/components/AppPage.vue',
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false,
        },
        vuetify: {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
        'vuetify/styles': {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
      },
      format: 'esm'
    }),
  ],
  build: {
    target: 'esnext',   // 必须设置为esnext以支持顶层await
    minify: 'terser',      // 开发阶段建议关闭混淆
    cssCodeSplit: true, // 改为true以便能分离样式文件
    rollupOptions: {
      output: {
        chunkFileNames: chunk => (isPluginChunk(chunk) ? 'assets/__federation_chunk_[name]-[hash].js' : 'assets/[name]-[hash].js'),
        assetFileNames: asset => {
          const names = asset.names || (asset.name ? [asset.name] : [])
          const isPluginCss = names.some(name => name.endsWith('.css') && !/^(index|styles)/.test(name))
          return isPluginCss && !names.some(name => name.startsWith('__federation_'))
            ? 'assets/__federation_chunk_[name]-[hash][extname]'
            : 'assets/[name]-[hash][extname]'
        },
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: '/* 覆盖vuetify样式 */',
      }
    },
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: {
            charset: (atRule) => {
              if (atRule.name === 'charset') {
                atRule.remove();
              }
            }
          }
        },
        // 只在非开发环境下启用 vuetify 样式过滤
        ...(process.env.NODE_ENV !== 'development' ? [{
          postcssPlugin: 'vuetify-filter',
          Root(root) {
            // 过滤掉所有vuetify相关的CSS
            root.walkRules(rule => {
              if (rule.selector && (
                rule.selector.includes('.v-') ||
                rule.selector.includes('.mdi-'))) {
                rule.remove();
              }
            });
          }
        }] : [])
      ]
    }
  },
  server: {
    port: 5001,   // 使用不同于主应用的端口
    cors: true,   // 启用CORS
    origin: 'http://localhost:5001'
  },
})