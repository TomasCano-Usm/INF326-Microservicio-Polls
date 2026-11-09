import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const gatewayTarget =
  process.env.VITE_GATEWAY_PROXY_TARGET || 'http://localhost:5000';

const gatewayProxy = {
  '/graphql': {
    target: gatewayTarget,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: gatewayProxy,
  },
  preview: {
    port: 3000,
    host: true,
    proxy: gatewayProxy,
  },
});
