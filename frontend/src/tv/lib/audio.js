import { writable } from 'svelte/store';
import { gameState } from '../../lib/stores/gameState.js';
import { createPlayer } from '../../lib/audioPlayer.js';

// TV-specific WS connection + voice-call playback. /tv is the audio-role
// device by default (this is the one meant to be heard next to the board),
// so its socket carries a `?role=audio` query param and also receives
// `type: 'sound'` play instructions alongside the normal state payload —
// unlike Home's plain gameState.connect(), which never needs either.
// Reuses the shared `gameState` store so the players/elimination derived
// stores work identically on both apps.

export const audioOn = writable(true);
export const connDot = writable(false);

let socket = null;
let currentRole = null;
const player = createPlayer();

function handleSound(inst) {
  let on;
  audioOn.subscribe((v) => (on = v))();
  if (on) player.handle(inst);
}

function handleSoundBatch(msg) {
  for (const item of msg.items) handleSound({ ...item, v: msg.v });
}

export function connect() {
  let on;
  audioOn.subscribe((v) => (on = v))();
  currentRole = on;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${proto}//${location.host}/ws${on ? '?role=audio' : ''}`);
  socket.onopen = () => connDot.set(true);
  socket.onclose = () => { connDot.set(false); setTimeout(connect, 2000); };
  socket.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'sound') { handleSound(msg); return; }
    if (msg.type === 'sound_batch') { handleSoundBatch(msg); return; }
    gameState.set(msg);
  };
}

export function toggleAudio() {
  audioOn.update((v) => {
    const next = !v;
    if (next) {
      player.unlock();
    } else {
      player.stopAll();
    }
    return next;
  });
  // Reconnect so the server-side audio role matches the toggle.
  try { socket?.close(); } catch (_) {}
}

export function primeAutoplay() {
  player.unlock();
}
