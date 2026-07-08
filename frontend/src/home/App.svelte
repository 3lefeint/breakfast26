<script>
  import { onMount } from 'svelte';
  import { connect, wsStatus } from '../lib/stores/gameState.js';
  import { health, startHealthPolling } from '../lib/stores/health.js';
  import { route } from '../lib/router.js';
  import AppHeader from '../lib/components/AppHeader.svelte';
  import DevUnlockCelebration from '../lib/components/DevUnlockCelebration.svelte';
  import Home from './views/Home.svelte';
  import Elimination from './views/Elimination.svelte';
  import Players from './views/Players.svelte';
  import Stats from './views/Stats.svelte';
  import Settings from './views/Settings.svelte';

  onMount(() => {
    connect();
    startHealthPolling();
  });

  let connLabel = $derived(
    $wsStatus === 'connected' ? 'Connected' : $wsStatus === 'reconnecting' ? 'Reconnecting…' : 'connecting…'
  );

  // Android-style hidden unlock: tap the version number DEV_TAP_THRESHOLD
  // times in a row (within DEV_TAP_WINDOW_MS of each other) to reveal
  // Settings' Dev tab for this run, without touching config.toml — POST
  // /api/dev/unlock is in-memory only server-side, so it's gone again on
  // the next restart, same as this counter is gone on the next page load.
  const DEV_TAP_THRESHOLD = 7;
  const DEV_TAP_WINDOW_MS = 1500;
  const DEV_CELEBRATION_MS = 2500;
  let devTapCount = 0;
  let devTapTimer = null;
  let showDevCelebration = $state(false);
  let devCelebrationTimer = null;

  async function onVersionTap() {
    clearTimeout(devTapTimer);
    devTapCount += 1;
    devTapTimer = setTimeout(() => { devTapCount = 0; }, DEV_TAP_WINDOW_MS);
    if (devTapCount < DEV_TAP_THRESHOLD) return;
    devTapCount = 0;
    try {
      await fetch('/api/dev/unlock', { method: 'POST' });
      clearTimeout(devCelebrationTimer);
      showDevCelebration = true;
      devCelebrationTimer = setTimeout(() => { showDevCelebration = false; }, DEV_CELEBRATION_MS);
    } catch (_) {
      // network hiccup — nothing to show, just tap again
    }
  }
</script>

<AppHeader />

{#if showDevCelebration}
  <DevUnlockCelebration />
{/if}

<main>
  {#if $route === 'elimination'}
    <Elimination />
  {:else if $route === 'players'}
    <Players />
  {:else if $route === 'stats'}
    <Stats />
  {:else if $route === 'settings'}
    <Settings />
  {:else}
    <Home />
  {/if}
</main>

<footer>
  <span class="dot-group">
    <span><span class="conn-dot" class:ok={$wsStatus === 'connected'}></span><span class="conn-label">{connLabel}</span></span>
    <span><span class="conn-dot" class:ok={$health.mqttOk}></span><span class="conn-label">MQTT</span></span>
    <span><span class="conn-dot" class:ok={$health.autodartsOk}></span><span class="conn-label">Autodarts</span></span>
  </span>
  <button type="button" class="version-info" onclick={onVersionTap}>{$health.version ? `v${$health.version} · ${$health.releaseDate}` : ''}</button>
</footer>

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared
     with TV/Audio). Vite mounts this app into <div id="app"> inside
     <body>, not body's direct children like the old template — so the
     flex-column page layout has to target #app instead of body.
     #app is pinned to exactly one viewport tall (not min-height) so
     header/footer never move — only <main> scrolls internally when its
     content is taller than the space between them. */
  :global(#app) {
    height: 100vh;
    display: flex;
    flex-direction: column;
    background:
      radial-gradient(ellipse 900px 500px at 15% -10%, color-mix(in srgb, var(--accent) 10%, transparent), transparent),
      radial-gradient(ellipse 700px 500px at 100% 0%, color-mix(in srgb, var(--accent) 6%, transparent), transparent);
  }
  main {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    width: 100%;
    max-width: 720px;
    margin: 0 auto;
    padding: 1.5rem 1.25rem;
    font-family: system-ui, sans-serif;
  }
  footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.6rem 1.25rem; background: var(--surface); border-top: 1px solid var(--border);
    font-size: 0.8rem; color: var(--muted); flex-shrink: 0;
  }
  .dot-group { display: flex; align-items: center; gap: 1rem; }
  .conn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); display: inline-block; margin-right: 5px; transition: background 0.3s; }
  .conn-dot.ok { background: var(--green); }
  .conn-label { font-size: 0.8rem; color: var(--muted); }
  .version-info {
    color: var(--muted); cursor: pointer; user-select: none;
    background: none; border: none; padding: 0; font: inherit;
  }
</style>
