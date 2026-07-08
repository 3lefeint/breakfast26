import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Multi-page build — Home app (index.html), TV app (tv.html), and
// the minimal audio-unlock page (audio.html) share everything under
// src/lib/ but are separate entry points, matching the app's split
// into three independently-loaded surfaces.
export default defineConfig({
  plugins: [svelte()],
  build: {
    rollupOptions: {
      input: {
        home: 'index.html',
        tv: 'tv.html',
        audio: 'audio.html',
      },
    },
  },
  server: {
    // Dev server proxies REST + WebSocket calls to the real running
    // backend (the local docker-compose deployment) so `npm run dev`
    // exercises real data instead of mocks.
    proxy: {
      '/api': 'http://localhost:8080',
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
});
