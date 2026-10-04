<script>
  import { onMount } from 'svelte';
  import { connect, wsStatus } from '../lib/stores/gameState.js';
  import { health, startHealthPolling } from '../lib/stores/health.js';
  import { route, navigate } from '../lib/router.js';
  import AppHeader from '../lib/components/AppHeader.svelte';
  import DevUnlockCelebration from '../lib/components/DevUnlockCelebration.svelte';
  import Home from './views/Home.svelte';
  import Elimination from './views/Elimination.svelte';
  import TargetBattle from './views/TargetBattle.svelte';
  import Killer from './views/Killer.svelte';
  import Players from './views/Players.svelte';
  import Profile from './views/Profile.svelte';
  import Stats from './views/Stats.svelte';
  import Settings from './views/Settings.svelte';
  import About from './views/About.svelte';

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

<AppHeader />

{#if showDevCelebration}
  <DevUnlockCelebration />
{/if}

<main>
  <div class="page">
    {#if $route === 'elimination'}
      <Elimination />
    {:else if $route === 'target-battle'}
      <TargetBattle />
    {:else if $route === 'killer'}
      <Killer />
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
    <span><span class="conn-dot" class:ok={$wsStatus === 'connected'}></span><span class="conn-label">{connLabel}</span></span>
    <span><span class="conn-dot" class:ok={$health.mqttOk}></span><span class="conn-label">MQTT</span></span>
    <span><span class="conn-dot" class:ok={$health.autodartsOk}></span><span class="conn-label">Autodarts</span></span>
  </span>
  <span class="version-group">
    <button type="button" class="version-info" onclick={onVersionTap}>{$health.version ? `v${$health.version}` : ''}</button>
    <button type="button" class="about-btn" aria-label="About" title="About" onclick={() => navigate('about')}>ℹ️</button>
  </span>
</footer>

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared
     with TV/Audio). Vite mounts this app into <div id="app"> inside
     <body>, not body's direct children like the old template — so the
     flex-column page layout has to target #app instead of body.
     The document scrolls, not <main>: #app is at least one viewport tall
     and grows with its content, so the page has its real height (full-page
     screenshots and print capture all of it, the wheel works anywhere in
     the window). Header and footer stay in view with position: sticky; the
     header comes from the shared AppHeader, so it is targeted from here
     and the TV and audio pages keep theirs. The content is centred in
     .page. */
  :global(#app) {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background:
      radial-gradient(ellipse 900px 500px at 15% -10%, color-mix(in srgb, var(--accent) 10%, transparent), transparent),
      radial-gradient(ellipse 700px 500px at 100% 0%, color-mix(in srgb, var(--accent) 6%, transparent), transparent);
  }
  :global(#app > header) {
    position: sticky;
    top: 0;
  }
  main {
    flex: 1;
    width: 100%;
    font-family: system-ui, sans-serif;
  }
  .page {
    max-width: 1100px;
    margin: 0 auto;
    padding: 1.5rem 1.25rem;
  }
  footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.6rem 1.25rem; background: var(--surface); border-top: 1px solid var(--border);
    font-size: 0.8rem; color: var(--muted); flex-shrink: 0;
    position: sticky; bottom: 0; z-index: 20;
  }
  .dot-group { display: flex; align-items: center; gap: 1rem; }
  .conn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); display: inline-block; margin-right: 5px; transition: background 0.3s; }
  .conn-dot.ok { background: var(--green); }
  .conn-label { font-size: 0.8rem; color: var(--muted); }
  .version-group { display: flex; align-items: center; gap: 0.5rem; }
  .version-info {
    color: var(--muted); cursor: pointer; user-select: none;
    background: none; border: none; padding: 0; font: inherit;
  }
  .about-btn { background: none; border: none; padding: 0; font: inherit; cursor: pointer; opacity: 0.7; line-height: 1; }
  .about-btn:hover { opacity: 1; }
</style>
