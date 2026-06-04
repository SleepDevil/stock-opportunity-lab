import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'vendor-tanstack',
              test: /node_modules[\\/]@tanstack/,
              priority: 30
            },
            {
              name: 'vendor-ui',
              test: /node_modules[\\/](@mantine|lucide-react)/,
              priority: 20
            },
            {
              name: 'vendor-chart',
              test: /node_modules[\\/]lightweight-charts/,
              priority: 15
            },
            {
              name: 'vendor',
              test: /node_modules/,
              priority: 10
            }
          ]
        }
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000'
    }
  }
});
