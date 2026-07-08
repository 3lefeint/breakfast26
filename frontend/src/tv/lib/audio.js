import { writable } from 'svelte/store';
import { gameState } from '../../lib/stores/gameState.js';

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
let voicePlaying = null;
let ambientPlaying = null;
const voiceQueue = [];

function soundUrl(f, v) {
  return '/api/sound/' + encodeURIComponent(f) + (v ? '?v=' + encodeURIComponent(v) : '');
}

function playNextVoice() {
  if (voicePlaying || voiceQueue.length === 0) return;
  const inst = voiceQueue.shift();
  // A batch item already has its Audio element under construction (see
  // handleSoundBatch) — reuse it instead of only starting the fetch now,
  // so batched phrases don't pay serial fetch latency between each other.
  const a = inst.audio || new Audio(soundUrl(inst.file, inst.v));
  a.volume = Math.max(0, Math.min(1, inst.volume ?? 1));
  voicePlaying = a;
  const done = () => { if (voicePlaying === a) voicePlaying = null; playNextVoice(); };
  a.onended = done;
  a.onerror = done;
  a.play().catch(done);
}

function stopVoice() {
  voiceQueue.length = 0;
  if (voicePlaying) {
    voicePlaying.onended = null;
    voicePlaying.onerror = null;
    voicePlaying.pause();
    voicePlaying = null;
  }
}

function handleSound(inst) {
  let on;
  audioOn.subscribe((v) => (on = v))();
  if (!on) return;
  if (inst.channel === 'ambient') {
    if (ambientPlaying) ambientPlaying.pause();
    const a = new Audio(soundUrl(inst.file, inst.v));
    a.volume = Math.max(0, Math.min(1, inst.volume ?? 1));
    ambientPlaying = a;
    a.play().catch(() => {});
    return;
  }
  if (inst.break_last) stopVoice();
  voiceQueue.push(inst);
  playNextVoice();
}

function handleSoundBatch(msg) {
  let on;
  audioOn.subscribe((v) => (on = v))();
  if (!on) return;
  // Construct + load every item's Audio element immediately, in parallel,
  // instead of one fetch-then-play step at a time — the whole sequence is
  // already known up front, so there's no reason to wait for phrase N's
  // playback to end before even starting phrase N+1's fetch.
  for (const item of msg.items) {
    const inst = { ...item, v: msg.v };
    if (inst.channel === 'ambient') {
      if (ambientPlaying) ambientPlaying.pause();
      const a = new Audio(soundUrl(inst.file, inst.v));
      a.volume = Math.max(0, Math.min(1, inst.volume ?? 1));
      ambientPlaying = a;
      a.play().catch(() => {});
      continue;
    }
    if (inst.break_last) stopVoice();
    const a = new Audio(soundUrl(inst.file, inst.v));
    a.volume = Math.max(0, Math.min(1, inst.volume ?? 1));
    a.load();
    voiceQueue.push({ ...inst, audio: a });
  }
  playNextVoice();
}

const SILENT_WAV = 'data:audio/wav;base64,UklGRkQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YSAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==';

function unlockAutoplay() {
  new Audio(SILENT_WAV).play().catch(() => {});
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
      unlockAutoplay();
    } else {
      stopVoice();
      if (ambientPlaying) ambientPlaying.pause();
    }
    return next;
  });
  // Reconnect so the server-side audio role matches the toggle.
  try { socket?.close(); } catch (_) {}
}

export function primeAutoplay() {
  unlockAutoplay();
}
