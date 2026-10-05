<script>
  // Ports breakfast/web/templates/audio.html — the minimal audio-unlock
  // page. A browser tab left open
  // on the device wired to the speakers; tapping the button unlocks
  // autoplay, then incoming voice/ambient calls just play here. Always
  // connects with role=audio (unlike Home, which never needs sound, and
  // TV, where the role is a user toggle).
  import { onMount } from 'svelte';
  import AppHeader from '../lib/components/AppHeader.svelte';
  import Aurora from '../lib/components/Aurora.svelte';
  import { createPlayer } from '../lib/audioPlayer.js';

  let unlocked = $state(false);
  let connOk = $state(false);
  let queueLen = $state(0);
  let log = $state([]); // newest first, capped at 50

  const player = createPlayer({
    onQueueChange: (n) => { queueLen = n; },
    onError: (msg) => {
      console.warn('[audio] ' + msg);
      log = [{ channel: 'error', text: `${new Date().toLocaleTimeString()}  ${msg}` }, ...log].slice(0, 50);
    },
  });

  function logLine(inst) {
    const flags = inst.break_last ? ' [break]' : '';
    const line = { channel: inst.channel, text: `${new Date().toLocaleTimeString()}  ${inst.channel}  ${inst.file}${flags}` };
    log = [line, ...log].slice(0, 50);
  }

  function handleSound(inst) {
    logLine(inst);
    if (unlocked) player.handle(inst);
  }

  function handleSoundBatch(msg) {
    for (const item of msg.items) handleSound({ ...item, v: msg.v });
  }

  function unlock() {
    player.unlock();
    unlocked = true;
  }

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws?role=audio`);
    ws.onopen = () => { connOk = true; };
    ws.onclose = () => { connOk = false; setTimeout(connect, 2000); };
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === 'sound') handleSound(msg);
      else if (msg.type === 'sound_batch') handleSoundBatch(msg);
    };
  }

  async function applyTheme() {
    try {
      const cfg = await fetch('/api/config').then((r) => r.json());
      if (cfg.web?.theme) document.documentElement.dataset.theme = cfg.web.theme;
      if (cfg.web?.accent_color) document.documentElement.style.setProperty('--accent', cfg.web.accent_color);
    } catch (_) {
      // no config yet — keep default theme
    }
  }

  onMount(() => {
    applyTheme();
    connect();
  });
</script>

<Aurora />

<AppHeader>
  {#snippet left()}
    <span class="conn-dot" class:ok={connOk}></span>
    <span class="sep">audio output</span>
  {/snippet}
  {#snippet right()}
    <span class="queue-info">{queueLen ? `queue: ${queueLen}` : ''}</span>
  {/snippet}
</AppHeader>

<main>
  {#if !unlocked}
    <button id="unlockBtn" onclick={unlock}>🔊 Enable sound</button>
    <div class="status">Browsers block automatic audio until you interact with the
      page once. Click the button, then leave this tab open on the device
      connected to the speakers.</div>
  {:else}
    <div class="status"><span class="on">Sound enabled.</span> Leave this tab open — incoming calls play here.</div>
    <div class="log">
      {#each log as line}
        <div class={line.channel}>{line.text}</div>
      {/each}
    </div>
  {/if}
</main>

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared
     with Home/TV). Vite mounts this app into <div id="app"> inside
     <body>, not body's direct children like the old template — so the
     flex-column/align-items layout has to target #app instead of body. */
  :global(#app) { height: 100vh; display: flex; flex-direction: column; align-items: center; }
  .sep { font-size: 0.85rem; color: var(--muted); }
  .conn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); display: inline-block; transition: background 0.3s; }
  .conn-dot.ok { background: var(--green); }
  .queue-info { font-size: 0.85rem; color: var(--muted); }
  main {
    flex: 1; min-height: 0; overflow-y: auto;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 1.5rem; width: min(92vw, 480px);
  }
  #unlockBtn {
    font-size: 1.4rem; font-weight: 700; padding: 1.2rem 2.5rem;
    border: none; border-radius: 14px; background: var(--accent); color: #0c0c0f; cursor: pointer;
    box-shadow: 0 0 28px -6px var(--accent);
  }
  #unlockBtn:active { transform: scale(0.98); }
  .status { font-size: 1.05rem; color: var(--muted); text-align: center; }
  .status .on { color: var(--green); font-weight: 600; }
  .log {
    width: 100%; max-height: 40vh; overflow-y: auto;
    background: var(--glass); border: 1px solid var(--glass-border); border-radius: 14px; box-shadow: var(--glass-shadow);
    backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    padding: 0.7rem 0.9rem; font-family: ui-monospace, monospace; font-size: 0.78rem; color: var(--muted);
  }
  .log div { padding: 1px 0; }
  .log .voice { color: var(--text); }
  .log .ambient { color: var(--accent); }
  .log .error { color: var(--red); }
</style>
