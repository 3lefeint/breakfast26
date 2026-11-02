<script>
  // Records a sound with the microphone of the browser (getUserMedia and MediaRecorder): a start and a stop button, the time
  // and a level meter. The result goes to the sound editor like a file picked from the computer; the server turns it into an
  // mp3 when it is saved there, and nothing is stored before.
  import { onDestroy } from 'svelte';
  import { t } from '../../lib/i18n.js';

  let { onrecorded, oncancel } = $props();

  const MAX_SECONDS = 120;
  const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];

  let phase = $state('idle');          // idle, recording, recorded
  let error = $state('');
  let seconds = $state(0);
  let level = $state(0);               // 0 to 1, the highest sample of the last moment
  let clipping = $state(false);
  let result = $state(null);           // { file, url } of the finished recording

  let stream = null;
  let recorder = null;
  let chunks = [];
  let ctx = null;
  let raf = 0;
  let began = 0;

  const extension = (type) => (type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm');

  async function start() {
    error = '';
    discard();
    try {
      // The raw sound: the editor sets the loudness itself and has its own noise reduction.
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    } catch (e) {
      error = e?.name === 'NotAllowedError' ? t('The microphone is not allowed. Allow it for this page in the browser.')
        : t('No microphone was found.');
      return;
    }
    const type = TYPES.find((x) => MediaRecorder.isTypeSupported(x)) || '';
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };
    recorder.onstop = finish;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    began = performance.now();
    recorder.start();
    phase = 'recording';
    const tick = () => {
      if (phase !== 'recording') return;
      analyser.getByteTimeDomainData(samples);
      let top = 0;
      for (const v of samples) top = Math.max(top, Math.abs(v - 128) / 128);
      level = top;
      clipping = top >= 0.98;
      seconds = (performance.now() - began) / 1000;
      if (seconds >= MAX_SECONDS) { stop(); return; }
      raf = requestAnimationFrame(tick);
    };
    tick();
  }

  function stop() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  function release() {
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    try { ctx?.close(); } catch (_) { /* already closed */ }
    ctx = null;
    level = 0;
    clipping = false;
  }

  function finish() {
    release();
    const type = recorder?.mimeType || chunks[0]?.type || 'audio/webm';
    const blob = new Blob(chunks, { type });
    chunks = [];
    if (!blob.size) { phase = 'idle'; error = t('Nothing was recorded.'); return; }
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
    result = { file: new File([blob], `recording-${stamp}.${extension(type)}`, { type }), url: URL.createObjectURL(blob) };
    phase = 'recorded';
  }

  function discard() {
    if (result) URL.revokeObjectURL(result.url);
    result = null;
    seconds = 0;
    phase = 'idle';
  }

  function use() {
    const file = result.file;
    URL.revokeObjectURL(result.url);
    result = null;
    onrecorded?.(file);
  }

  function close() {
    if (recorder && recorder.state !== 'inactive') { recorder.onstop = null; recorder.stop(); }
    release();
    if (result) URL.revokeObjectURL(result.url);
    oncancel?.();
  }

  onDestroy(() => { if (recorder && recorder.state !== 'inactive') { recorder.onstop = null; recorder.stop(); } release(); });

  const clock = (value) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') close(); }} />

<div class="modal-back" role="presentation" onpointerdown={(e) => { if (e.target === e.currentTarget) close(); }}>
  <div class="modal" role="dialog" aria-modal="true" aria-label={t('Record a sound')}>
    <div class="modal-title">{t('Record a sound')}</div>
    <div class="meter" role="progressbar" aria-label={t('Input level')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(level * 100)}>
      <div class="bar" class:clip={clipping} style:width="{Math.round(level * 100)}%"></div>
    </div>
    <div class="clock">{clock(seconds)} <span class="note">/ {clock(MAX_SECONDS)}</span></div>
    <audio controls src={result?.url}></audio>
    <div class="msg">{error}</div>
    <div class="actions">
      {#if phase === 'recording'}
        <button type="button" class="act primary" onclick={stop}>■ {t('Stop')}</button>
      {:else}
        <button type="button" class="act primary" onclick={start}>● {phase === 'recorded' ? t('Record again') : t('Record')}</button>
      {/if}
      <span class="spacer"></span>
      <button type="button" class="act" onclick={close}>{t('Cancel')}</button>
      <button type="button" class="act primary" onclick={use} disabled={phase !== 'recorded'}>{t('Edit the recording')}</button>
    </div>
    <span class="note">{t('The recording is stored only when you save it in the editor.')}</span>
  </div>
</div>

<style>
  .modal-back { position: fixed; inset: 0; z-index: 1100; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.55); }
  .modal {
    display: flex; flex-direction: column; gap: 0.7rem; width: min(26rem, calc(100vw - 2rem)); padding: 1rem 1.2rem;
    border-radius: 12px; background: var(--bg, #0f1115); border: 1px solid var(--glass-border); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
  .modal-title { font-size: 0.8rem; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
  .meter { height: 0.7rem; border-radius: 999px; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--glass-border); overflow: hidden; }
  .bar { height: 100%; background: var(--accent); transition: width 0.05s linear; }
  .bar.clip { background: var(--red); }
  .clock { font-size: 1.4rem; font-variant-numeric: tabular-nums; color: var(--text); }
  audio { width: 100%; height: 2.2rem; }
  .msg { min-height: 1.2rem; font-size: 0.8rem; color: var(--yellow); }
  .actions { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .spacer { flex: 1; }
  .note { font-size: 0.75rem; color: var(--muted); }
  .act {
    background: rgba(0, 0, 0, 0.25); border: 1px solid var(--glass-border); border-radius: 6px; color: var(--muted);
    padding: 0.25rem 0.75rem; font-family: inherit; font-size: 0.8rem; cursor: pointer;
  }
  .act:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
  .act.primary { color: var(--text); border-color: var(--accent); }
  .act:disabled { opacity: 0.45; cursor: default; }
</style>
