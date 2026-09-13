import {defineConfig, loadEnv} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({mode}) => {
  const environment = loadEnv(mode, '.', '');
  const proxyTarget =
    environment.DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000';

  const configuredHosts = environment.DEV_ALLOWED_HOSTS
    ?.split(',')
    .map(host => host.trim())
    .filter(Boolean);

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      allowedHosts: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
    },
  };
});