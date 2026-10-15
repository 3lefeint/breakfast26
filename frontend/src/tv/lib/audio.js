import { writable, get } from 'svelte/store';
import { gameState } from '../../lib/stores/gameState.js';
import { createPlayer } from '../../lib/audioPlayer.js';
import { announceAchievement } from '../../lib/stores/achievementQueue.js';

// The TV view's WS connection + voice-call playback. The TV view is the audio-role device by default
// (the one meant to be heard next to the board), so while it is shown it holds a socket with a `?role=audio`
// query param that also receives `type: 'sound'` play instructions alongside the normal state payload.
// Home's own socket never needs either. Reuses the shared `gameState` store so the derived stores work
// identically in both views.

export const audioOn = writable(true);
export const connDot = writable(false);
// True while the browser keeps the voice calls silent, until the page has been clicked.
export const locked = writable(true);

let socket = null;
let wanted = false;
let retry = null;
const player = createPlayer({ onStateChange: (state) => locked.set(state !== 'running') });

function handleSound(inst) {
  // A call that arrives while the browser blocks the sound is dropped; played after the unlock it would
  // come too late, and several of them would sound at once.
  if (get(locked) || !get(audioOn)) return;
  player.handle(inst);
}

function handleSoundBatch(msg) {
  for (const item of msg.items) handleSound({ ...item, v: msg.v });
}

function open() {
  if (!wanted || (socket && socket.readyState <= 1)) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws${get(audioOn) ? '?role=audio' : ''}`);
  socket = ws;
  ws.onopen = () => connDot.set(true);
  ws.onclose = () => {
    if (socket !== ws) return;
    connDot.set(false);
    if (wanted) retry = setTimeout(open, 2000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'sound') { handleSound(msg); return; }
    if (msg.type === 'sound_batch') { handleSoundBatch(msg); return; }
    if (msg.type === 'achievement') { announceAchievement(msg); return; }
    gameState.set(msg);
  };
}

// The TV view plays the voice calls: it holds its own socket with the audio role while it is shown.
export function startAudio() {
  wanted = true;
  open();
}

export function stopAudio() {
  wanted = false;
  clearTimeout(retry);
  player.stopAll();
  const ws = socket;
  socket = null;
  try { ws?.close(); } catch (_) {}
  connDot.set(false);
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
