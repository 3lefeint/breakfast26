<script>
  import { t } from '../lib/i18n.js';
  import { onMount } from 'svelte';
  import { gameState } from '../lib/stores/gameState.js';
  import { players } from '../lib/stores/players.js';
  import { elimination } from '../lib/stores/elimination.js';
  import { targetBattle } from '../lib/stores/targetBattle.js';
  import { killer } from '../lib/stores/killer.js';
  import { fieldTraining } from '../lib/stores/fieldTraining.js';
  import { blackBelt } from '../lib/stores/blackBelt.js';
  import { checkoutTraining } from '../lib/stores/checkoutTraining.js';
  import { online } from '../lib/stores/online.js';
  import { cap } from '../lib/util.js';
  import { connect, toggleAudio, audioOn, connDot, primeAutoplay } from './lib/audio.js';
  import { health, startHealthPolling } from '../lib/stores/health.js';
  import AppHeader from '../lib/components/AppHeader.svelte';
  import Aurora from '../lib/components/Aurora.svelte';
  import AchievementBanner from './views/AchievementBanner.svelte';
  import X01View from './views/X01View.svelte';
  import IdleView from './views/IdleView.svelte';
  import EliminationTv from './views/EliminationTv.svelte';
  import EliminationFinishedTv from './views/EliminationFinishedTv.svelte';
  import TargetBattleTv from './views/TargetBattleTv.svelte';
  import TargetBattleFinishedTv from './views/TargetBattleFinishedTv.svelte';
  import KillerTv from './views/KillerTv.svelte';
  import KillerFinishedTv from './views/KillerFinishedTv.svelte';
  import FieldTrainingTv from './views/FieldTrainingTv.svelte';
  import FieldTrainingFinishedTv from './views/FieldTrainingFinishedTv.svelte';
  import BlackBeltTv from './views/BlackBeltTv.svelte';
  import BlackBeltFinishedTv from './views/BlackBeltFinishedTv.svelte';
  import CheckoutTrainingTv from './views/CheckoutTrainingTv.svelte';
  import CheckoutTrainingFinishedTv from './views/CheckoutTrainingFinishedTv.svelte';

  onMount(() => {
    connect();
    startHealthPolling();
    primeAutoplay();
  });

  // After a rematch every site goes back to the lobby on Home, where it picks its own players.
  let lastPhase = null;
  $effect(() => {
    const phase = $online?.phase ?? null;
    if (lastPhase === 'ended' && phase === 'lobby') window.location.href = '/#elimination';
    lastPhase = phase;
  });

  let game = $derived($gameState.game || {});
  let sessionStats = $derived($gameState.session_stats || {});

  let matchMeta = $derived.by(() => {
    if ($elimination && ($elimination.state === 'finished' || $elimination.active)) return t('Elimination');
    if ($targetBattle && ($targetBattle.state === 'finished' || $targetBattle.active)) return t('Target Battle');
    if ($killer && ($killer.state === 'finished' || $killer.active)) return t('Killer');
    if ($fieldTraining && ($fieldTraining.state === 'finished' || $fieldTraining.active)) return t('Field Training');
    if ($blackBelt && ($blackBelt.state === 'finished' || $blackBelt.active)) return t('Black Belt');
    if ($checkoutTraining && ($checkoutTraining.state === 'finished' || $checkoutTraining.active)) return t('Checkout Training');
    if (!game.match_started) return game.board_status ? `${t('Board')}: ${game.board_status}` : '—';
    const legLabel = game.current_leg > 1 ? ` · ${t('Leg {n}', { n: game.current_leg })}` : '';
    return [game.game_mode, game.points_start ? `${game.points_start} ${t('pts')}` : null].filter(Boolean).join(' · ') + legLabel;
  });

  let view = $derived.by(() => {
    if ($elimination && $elimination.state === 'finished') return 'elim-finished';
    if ($elimination && $elimination.active) return 'elim-live';
    if ($targetBattle && $targetBattle.state === 'finished') return 'tb-finished';
    if ($targetBattle && $targetBattle.active) return 'tb-live';
    if ($killer && $killer.state === 'finished') return 'killer-finished';
    if ($killer && $killer.active) return 'killer-live';
    if ($fieldTraining && $fieldTraining.state === 'finished') return 'ft-finished';
    if ($fieldTraining && $fieldTraining.active) return 'ft-live';
    if ($blackBelt && $blackBelt.state === 'finished') return 'bb-finished';
    if ($blackBelt && $blackBelt.active) return 'bb-live';
    if ($checkoutTraining && $checkoutTraining.state === 'finished') return 'co-finished';
    if ($checkoutTraining && $checkoutTraining.active) return 'co-live';
    if (game.match_started) return 'x01';
    return 'idle';
  });

  // Always-visible board-readiness indicator, independent of whether a
  // match is active — matchMeta above already goes dark on board_status
  // the moment a leg starts, which is exactly when a stuck takeout matters
  // most. Green: ready to throw. Yellow: normal, expected, not throwable
  // right now. Red: a real problem. Grey: no status yet, or one we don't
  // recognize — never guess green for something we don't know.
  const BOARD_STATUS_COLOR = {
    // Autodarts' own raw status vocabulary — forwarded unmodified by the
    // backend (breakfast/board_status.py), this is what actually arrives
    // for most events now.
    'Throw': 'green',
    'Takeout': 'yellow',
    'Takeout in progress': 'yellow',
    // Fallback event-name-based strings, used only for events that don't
    // carry Autodarts' own status field.
    'Board Started': 'green',
    'Takeout Finished': 'green',
    'Calibration Finished': 'green',
    'Manual reset': 'green',
    'Takeout Started': 'yellow',
    'Calibration Started': 'yellow',
    'Board Starting': 'yellow',
    'Board Stopped': 'red',
    'Board Stopping': 'red',
    'Board Disconnected': 'red',
  };
  let boardStatusColor = $derived(BOARD_STATUS_COLOR[game.board_status] || 'grey');
  // 'grey' (no status yet, or an unrecognized one) keeps the header's
  // default subtle accent glow instead of claiming a color we're not
  // actually sure of.
  let headerGlow = $derived(boardStatusColor === 'grey' ? null : boardStatusColor);
</script>

<Aurora />

<AchievementBanner />

<AppHeader title={matchMeta} glowColor={headerGlow}>
  {#snippet right()}
    <button type="button" class="sound-btn" title={t('Play voice calls on this device')} onclick={toggleAudio}>
      {$audioOn ? '🔊' : '🔇'}
    </button>
  {/snippet}
</AppHeader>

{#if view === 'idle'}
  {#if $gameState.board_darts}
    <IdleView darts={$gameState.board_darts} />
  {:else}
    <div id="idle">{t('Waiting for match…')}</div>
  {/if}
{:else if view === 'x01'}
  <div id="active">
    <X01View {game} {sessionStats} hasCloudControl={!!$gameState.has_cloud_control} boardDarts={$gameState.board_darts} />
  </div>
{:else if view === 'elim-live'}
  <div id="activeElim">
    <EliminationTv elimination={$elimination} winsFor={$players.winsFor} boardDarts={$gameState.board_darts} online={$online} />
  </div>
{:else if view === 'elim-finished'}
  <EliminationFinishedTv elimination={$elimination} online={$online} />
{:else if view === 'tb-live'}
  <div id="activeElim">
    <TargetBattleTv tb={$targetBattle} />
  </div>
{:else if view === 'tb-finished'}
  <TargetBattleFinishedTv tb={$targetBattle} />
{:else if view === 'killer-live'}
  <div id="activeElim">
    <KillerTv killer={$killer} />
  </div>
{:else if view === 'killer-finished'}
  <KillerFinishedTv killer={$killer} />
{:else if view === 'ft-live'}
  <div id="activeElim">
    <FieldTrainingTv ft={$fieldTraining} />
  </div>
{:else if view === 'ft-finished'}
  <FieldTrainingFinishedTv ft={$fieldTraining} />
{:else if view === 'bb-live'}
  <div id="activeElim">
    <BlackBeltTv bb={$blackBelt} />
  </div>
{:else if view === 'bb-finished'}
  <BlackBeltFinishedTv bb={$blackBelt} />
{:else if view === 'co-live'}
  <div id="activeElim">
    <CheckoutTrainingTv co={$checkoutTraining} />
  </div>
{:else if view === 'co-finished'}
  <CheckoutTrainingFinishedTv co={$checkoutTraining} />
{/if}

<footer>
  <span class="dot-group">
    <span><span class="conn-dot" class:ok={$connDot}></span><span class="conn-label">WS</span></span>
    <span><span class="conn-dot" class:ok={$health.mqttOk}></span><span class="conn-label">{t('MQTT')}</span></span>
    <span><span class="conn-dot" class:ok={$health.autodartsOk}></span><span class="conn-label">{t('Autodarts')}</span></span>
  </span>
  <span class="version-info">{$health.version ? `v${$health.version} · ${($health.releaseDate ?? '').slice(0, 10)}` : ''}</span>
</footer>

<style>
  /* html/body's height/background/reset come from lib/theme.css (shared
     with Home/Audio). Vite mounts this app into <div id="app"> inside
     <body> though, not body's direct children like the old templates —
     so the flex-column page layout has to target #app instead of body,
     otherwise flex:1 on #idle/#active/etc. has no effect and the footer
     ends up sitting right after the content instead of at the bottom. */
  :global(html), :global(body) { overflow: hidden; }
  /* On phone-width viewports, clipping (overflow: hidden) loses
     content that doesn't fit a wide-TV layout — allow vertical scrolling
     instead so nothing is simply unreachable. */
  @media (max-width: 480px) {
    :global(html), :global(body) { overflow-y: auto; }
  }
  :global(#app) { min-height: 100vh; display: flex; flex-direction: column; }
  .sound-btn { cursor: pointer; user-select: none; font-size: 1.1rem; background: none; border: none; color: inherit; font-family: inherit; padding: 0; }
  #idle {
    flex: 1; display: flex; align-items: center; justify-content: center;
    font-size: 2rem; color: var(--muted); font-weight: 300; letter-spacing: 0.05em;
  }
  #active, #activeElim { flex: 1; display: flex; min-height: 0; }
  #active { flex-direction: column; }
  #activeElim { flex-direction: row; gap: 1.5vw; padding: 1.3vw 2vw; }
  footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 1.5rem; height: 2.1rem; background: var(--glass); border-top: 1px solid var(--glass-border);
    backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); box-shadow: var(--glass-bar-shadow);
    font-size: 0.8rem; color: var(--muted); flex-shrink: 0;
  }
  .dot-group { display: flex; align-items: center; gap: 1.25rem; }
  .conn-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--red); display: inline-block; margin-right: 7px; transition: background 0.3s; }
  .conn-dot.ok { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .conn-label { font-size: 0.8rem; color: var(--text); }
  .version-info { color: var(--muted); }
</style>
