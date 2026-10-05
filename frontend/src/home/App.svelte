<script>
  import { onMount } from 'svelte';
  import { connect, wsStatus, gameState } from '../lib/stores/gameState.js';
  import { health, startHealthPolling } from '../lib/stores/health.js';
  import { route, navigate } from '../lib/router.js';
  import Aurora from '../lib/components/Aurora.svelte';
  import Icon from '../lib/components/Icon.svelte';
  import Sidebar from './shell/Sidebar.svelte';
  import TopBar from './shell/TopBar.svelte';
  import DevUnlockCelebration from '../lib/components/DevUnlockCelebration.svelte';
  import Home from './views/Home.svelte';
  import Elimination from './views/Elimination.svelte';
  import TargetBattle from './views/TargetBattle.svelte';
  import FieldTraining from './views/FieldTraining.svelte';
  import BlackBelt from './views/BlackBelt.svelte';
  import Killer from './views/Killer.svelte';
  import Players from './views/Players.svelte';
  import Profile from './views/Profile.svelte';
  import Stats from './views/Stats.svelte';
  import Settings from './views/Settings.svelte';
  import About from './views/About.svelte';

  let boardAddress = $state(null);

  onMount(async () => {
    connect();
    startHealthPolling();
    try {
      const r = await fetch('/api/board-address').then((res) => res.json());
      if (r.address) boardAddress = r.address;
    } catch (_) {
      // no board manager configured: the Board entry stays disabled
    }
  });

  // The board stream is connected while the board sends its darts (null otherwise).
  let boardConnected = $derived($gameState.board_darts != null);

  let connLabel = $derived(
    $wsStatus === 'connected' ? 'Connected' : $wsStatus === 'reconnecting' ? 'Reconnecting…' : 'connecting…'
  );

  // Android-style hidden unlock: tap the version number DEV_TAP_THRESHOLD
  // times in a row (within DEV_TAP_WINDOW_MS of each other) to reveal
  // Settings' Dev tab for this run, without touching config.toml — POST
  // /api/dev/unlock is in-memory only server-side, so it's gone again on
  // the next restart, same as this counter is gone on the next page load.
  const DEV_TAP_THRESHOLD = 5;
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

<Aurora />

{#if showDevCelebration}
  <DevUnlockCelebration />
{/if}

<div class="shell">
  <TopBar {boardConnected} />
  <Sidebar route={$route} {boardAddress} />

  <main>
      <div class="page">
        {#if $route === 'elimination'}
          <Elimination />
        {:else if $route === 'target-battle'}
          <TargetBattle />
        {:else if $route === 'killer'}
          <Killer />
        {:else if $route === 'field-training'}
          <FieldTraining />
        {:else if $route === 'black-belt'}
          <BlackBelt />
        {:else if $route === 'players'}
          <Players />
        {:else if $route.startsWith('profile/')}
          <Profile name={decodeURIComponent($route.slice('profile/'.length))} />
        {:else if $route === 'stats'}
          <Stats />
        {:else if $route === 'settings'}
          <Settings />
        {:else if $route === 'about'}
          <About />
        {:else}
          <Home />
        {/if}
      </div>
  </main>

  <footer>
      <span class="dot-group">
        {#if $wsStatus !== 'connected'}
          <span><span class="conn-dot"></span><span class="conn-label">{connLabel}</span></span>
        {/if}
        <span><span class="conn-dot" class:ok={$health.mqttOk}></span><span class="conn-label">MQTT</span></span>
        <span><span class="conn-dot" class:ok={$health.autodartsOk}></span><span class="conn-label">Autodarts</span></span>
      </span>
      <span class="version-group">
        <button type="button" class="version-info" onclick={onVersionTap}>{$health.version ? `v${$health.version}` : ''}</button>
        <button type="button" class="about-btn" aria-label="About" title="About" onclick={() => navigate('about')}><Icon name="info" size={16} /></button>
      </span>
  </footer>
</div>

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared with TV/Audio). The sidebar
     stays in view on the left, the top bar and the footer stick to the edges of the column, and the
     document scrolls, so the page has its real height (full-page screenshots and print capture all of
     it, the wheel works anywhere in the window). */
  :global(#app) { min-height: 100vh; }
  .shell {
    --header-h: 4.1rem; --footer-h: 2.6rem;
    display: grid; grid-template-columns: 240px minmax(0, 1fr); grid-template-rows: var(--header-h) 1fr var(--footer-h);
    min-height: 100vh;
  }
  main { grid-row: 2; grid-column: 2; min-width: 0; font-family: system-ui, sans-serif; }
  .page { max-width: 1600px; margin: 0 auto; padding: 2rem 2rem 2.5rem; }
  footer {
    position: sticky; bottom: 0; z-index: 40; flex-shrink: 0; grid-column: 1 / -1; grid-row: 3; height: var(--footer-h);
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 1.5rem; font-size: 0.8rem; color: var(--muted);
    background: var(--glass); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
    border-top: 1px solid var(--glass-border); box-shadow: var(--glass-bar-shadow);
  }
  .dot-group { display: flex; align-items: center; gap: 1.25rem; }
  .conn-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--red); display: inline-block; margin-right: 7px; transition: background 0.3s; }
  .conn-dot.ok { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .conn-label { font-size: 0.8rem; color: var(--text); }
  .version-group { display: flex; align-items: center; gap: 0.6rem; }
  .version-info { color: var(--muted); cursor: pointer; user-select: none; background: none; border: none; padding: 0; font: inherit; }
  .about-btn { background: none; border: none; padding: 0; color: var(--muted); cursor: pointer; line-height: 0; }
  .about-btn:hover { color: var(--text); }

  @media (max-width: 800px) {
    .shell { grid-template-columns: minmax(0, 1fr); grid-template-rows: var(--header-h) 1fr auto; --nav-h: 4.2rem; padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom)); }
    main { grid-column: 1; }
    .page { padding: 1.25rem 1rem 1.5rem; }
    /* The navigation is a bar along the bottom edge: keep the footer clear of it. */
    footer { position: static; grid-column: 1; height: auto; padding: 0.6rem 1rem; }
  }
</style>
