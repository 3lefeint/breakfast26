<script>
  import { t } from '../lib/i18n.js';
  import { onMount } from 'svelte';
  import { connect, wsStatus, gameState } from '../lib/stores/gameState.js';
  import { health, startHealthPolling } from '../lib/stores/health.js';
  import { route } from '../lib/router.js';
  import TvApp from '../tv/App.svelte';
  import Aurora from '../lib/components/Aurora.svelte';
  import Sidebar from './shell/Sidebar.svelte';
  import TopBar from './shell/TopBar.svelte';
  import ConfirmDialog from '../lib/components/ConfirmDialog.svelte';
  import { choiceDialog, alertDialog, answerConfirm } from '../lib/confirm.js';
  import DevUnlockCelebration from '../lib/components/DevUnlockCelebration.svelte';
  import Home from './views/Home.svelte';
  import Elimination from './views/Elimination.svelte';
  import TargetBattle from './views/TargetBattle.svelte';
  import FieldTraining from './views/FieldTraining.svelte';
  import BlackBelt from './views/BlackBelt.svelte';
  import WarmUp from './views/WarmUp.svelte';
  import CheckoutTrainer from './views/CheckoutTrainer.svelte';
  import CheckoutTraining from './views/CheckoutTraining.svelte';
  import CheckoutQuiz from './views/CheckoutQuiz.svelte';
  import SetupShots from './views/SetupShots.svelte';
  import Killer from './views/Killer.svelte';
  import X01 from './views/X01.svelte';
  import Tournament from './views/Tournament.svelte';
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
    $wsStatus === 'connected' ? t('Connected') : $wsStatus === 'reconnecting' ? t('Reconnecting…') : t('connecting…')
  );

  // A match that was in play when the program ended is offered here, on every client but the TV view. It goes on only
  // when someone chooses to; the dialog closes by itself when another client has chosen.
  const offered = new Set();
  let offerOpen = null;

  async function offerResume(offer) {
    offerOpen = offer.key;
    const answer = await choiceDialog(t('Resume open game?'),
      t('Resume'), t('Discard'));
    offerOpen = null;
    if (answer === null) return;
    const res = await fetch(`/api/resume/${offer.key}${answer ? '' : '/discard'}`, { method: 'POST' })
      .then((r) => r.json())
      .catch((e) => ({ error: String(e) }));
    if (res.error) alertDialog(t('Could not resume the match: {error}', { error: t(res.error) }));
  }

  $effect(() => {
    const offers = $gameState.resume ?? [];
    if (offerOpen && !offers.some((o) => o.key === offerOpen)) answerConfirm(null);
    if ($route === 'tv' || offerOpen) return;
    const next = offers.find((o) => !offered.has(o.key));
    if (next) {
      offered.add(next.key);
      offerResume(next);
    }
  });

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

<ConfirmDialog />

{#if $route === 'tv'}
  <TvApp {boardConnected} mqttOk={$health.mqttOk} autodartsOk={$health.autodartsOk} wsConnected={$wsStatus === 'connected'} {connLabel} />
{:else}
  <Aurora />

  {#if showDevCelebration}
    <DevUnlockCelebration />
  {/if}

  <div class="shell">
    <TopBar {boardConnected} mqttOk={$health.mqttOk} autodartsOk={$health.autodartsOk} wsConnected={$wsStatus === 'connected'} {connLabel} />
    <Sidebar route={$route} {boardAddress} version={$health.version} {onVersionTap} />

    <main>
        <div class="page">
          {#if $route === 'elimination'}
            <Elimination />
          {:else if $route === 'target-battle'}
            <TargetBattle />
          {:else if $route === 'killer'}
            <Killer />
          {:else if $route === 'x01'}
            <X01 />
          {:else if $route === 'tournament'}
            <Tournament />
          {:else if $route === 'field-training'}
            <FieldTraining />
          {:else if $route === 'black-belt'}
            <BlackBelt />
          {:else if $route === 'warm-up'}
            <WarmUp />
          {:else if $route === 'checkout-trainer'}
            <CheckoutTrainer />
          {:else if $route === 'checkout-training'}
            <CheckoutTraining />
          {:else if $route === 'checkout-quiz'}
            <CheckoutQuiz />
          {:else if $route === 'setup-shots'}
            <SetupShots />
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
  </div>
{/if}

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared with TV/Audio). The top bar
     sticks to the top edge, the navigation stays in view on the left, and the document scrolls, so
     the page has its real height (full-page screenshots and print capture all of it, the wheel works
     anywhere in the window). */
  :global(#app) { min-height: 100vh; }
  .shell {
    --header-h: 4.1rem;
    display: grid; grid-template-columns: 240px minmax(0, 1fr); grid-template-rows: var(--header-h) 1fr;
    min-height: 100vh;
  }
  main { grid-row: 2; grid-column: 2; min-width: 0; font-family: system-ui, sans-serif; }
  .page { max-width: 1600px; margin: 0 auto; padding: 2rem 2rem 2.5rem; }
  @media (max-width: 800px) {
    .shell { grid-template-columns: minmax(0, 1fr); grid-template-rows: var(--header-h) 1fr; --nav-h: 4.2rem; padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom)); }
    main { grid-column: 1; }
    .page { padding: 1.25rem 1rem 1.5rem; }
  }
</style>
