import { writable } from 'svelte/store';

// A single store fed directly by the existing /ws payload
// (_build_payload() in breakfast/web/server.py) — every component that
// reads from this store updates automatically, replacing the old
// vanilla-JS renderAll() dispatch list.
export const gameState = writable({});

// Mirrors index.html's connDot/connLabel — "connecting…" until the first
// open, "Connected" while open, "Reconnecting…" after a drop.
export const wsStatus = writable('connecting');

let socket = null;

export function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${proto}//${location.host}/ws`);

  socket.onopen = () => {
    wsStatus.set('connected');
  };

  socket.onmessage = (e) => {
    gameState.set(JSON.parse(e.data));
  };

  socket.onclose = () => {
    wsStatus.set('reconnecting');
    setTimeout(connect, 2000);
  };
}
