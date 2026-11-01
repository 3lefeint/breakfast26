import { createPlayer } from './audioPlayer.js';
import { announceSceneOverlay } from './stores/sceneOverlay.js';

// A scene test is heard and seen by the clients of the server (the /audio page, the TV view). When none is open the
// test would stay silent, so the page that starts it listens for a short while itself and shows the effects too. It is called from the click on
// "Test", which is also what lets the browser play sound.

const LISTEN_MS = 20000;

let player = null;
let socket = null;
let timer = null;
let soundOn = true;

// Another audio page that is open plays the sound of a test; then this page only shows the effects.
export function listenerSound(on) {
  soundOn = on;
}

export function listenForTest() {
  player = player || createPlayer({});
  player.unlock();
  soundOn = true;
  clearTimeout(timer);
  try { socket?.close(); } catch (_) { /* already closed */ }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws?role=audio`);
  socket = ws;
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'sound') { if (soundOn) player.handle(msg); }
    else if (msg.type === 'sound_batch') { if (soundOn) for (const item of msg.items) player.handle({ ...item, v: msg.v }); }
    else if (msg.type === 'scene_overlay') announceSceneOverlay(msg);
  };
  timer = setTimeout(() => { if (socket === ws) { socket = null; ws.close(); } }, LISTEN_MS);
  return new Promise((resolve) => {
    ws.onopen = resolve;
    ws.onerror = resolve;
  });
}
