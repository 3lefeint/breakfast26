// Records with the microphone of the browser (getUserMedia and MediaRecorder) and reports the level while it runs.
// The raw sound is recorded: the server sets the loudness itself.

export const MAX_SECONDS = 120;
const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];

// The browser allows the microphone only on https or on localhost.
export const canRecord = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
  && typeof MediaRecorder !== 'undefined';

// Starts recording. `onlevel(level, seconds)` is called on every frame (level 0 to 1), `onended(blob)` once after stop() (null when
// nothing was recorded) or when the longest time is reached. Throws what getUserMedia throws (`NotAllowedError`, `NotFoundError`).
// Returns { stop, cancel }: stop() ends the recording and hands it over, cancel() throws it away.
export async function startMic({ onlevel, onended, maxSeconds = MAX_SECONDS }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const type = TYPES.find((x) => MediaRecorder.isTypeSupported(x)) || '';
  const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);
  const began = performance.now();
  let raf = 0;
  let ended = false;
  let discard = false;

  const release = () => {
    cancelAnimationFrame(raf);
    stream.getTracks().forEach((track) => track.stop());
    try { ctx.close(); } catch (_) { /* already closed */ }
  };
  recorder.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };
  recorder.onstop = () => {
    release();
    if (discard || ended) return;
    ended = true;
    const blob = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || 'audio/webm' });
    onended(blob.size ? blob : null);
  };
  const stop = () => { if (recorder.state !== 'inactive') recorder.stop(); };
  const tick = () => {
    analyser.getByteTimeDomainData(samples);
    let top = 0;
    for (const v of samples) top = Math.max(top, Math.abs(v - 128) / 128);
    const seconds = (performance.now() - began) / 1000;
    onlevel?.(top, seconds);
    if (seconds >= maxSeconds) { stop(); return; }
    raf = requestAnimationFrame(tick);
  };
  recorder.start();
  tick();
  return {
    stop,
    cancel() { discard = true; stop(); if (recorder.state === 'inactive') release(); },
  };
}
