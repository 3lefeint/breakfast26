<script>
  import { confirmDialog } from '../../lib/confirm.js';
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import { api } from '../../lib/api.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Random checkout. The board fills most of the height with the darts of the attempt in
  // progress. Beside it: the score that is left (or has to be finished), the standard route if the
  // run shows it, the darts of the attempt (tap one to correct it), the progress of the run and how
  // the last attempt went. Finish ends the run early and keeps the attempts so far.
  import { rangeLabel, finishRun, stopRun, undoAttempt, percent, fieldName } from '../../lib/checkoutTraining.js';
  import Icon from '../../lib/components/Icon.svelte';
  import { gameState } from '../../lib/stores/gameState.js';
  import { isBoardStopped, shownName } from '../../lib/util.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import RouteChips from '../../lib/components/RouteChips.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { co } = $props();

  let live = $derived(co.live);
  let darts = $derived(co.round_darts?.[co.player] || []);
  let markers = $derived(darts.map((d, i) => (
    { n: `${i}`, label: d.points, x: d.x, y: d.y, color: co.color, avatar: { name: co.player, color: co.color } })));
  let shown = $derived(live && live.state === 'open' ? live.rest : (live && live.state === 'finished' ? 0 : co.score));
  let route = $derived(co.show_route ? (live && live.state === 'open' && co.rest_route ? co.rest_route : co.route) : null);
  let progress = $derived(Math.min(100, ((co.attempt - 1) / co.attempts) * 100));
  let last = $derived(co.last);

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (co.state !== 'playing') return;
    correctingIndex = index;
  }

  async function finish() {
    if (!await confirmDialog(co.results.length ? t('End the run now and keep the attempts so far?') : t('Cancel the run?'))) return;
    await finishRun();
    if (!co.results.length) navigate('home');
  }

  async function stop() {
    if (!await confirmDialog(t('Cancel the run without keeping it?'))) return;
    await stopRun();
    navigate('home');
  }

  async function resetBoard() {
    await api('POST', '/api/control/reset-board');
  }

  // The board stopped (camera standby): Start brings it back, until then there is nothing to reset.
  let boardStopped = $derived(isBoardStopped($gameState.game?.board_status));

  async function startBoard() {
    await api('POST', '/api/control/start-board');
  }

  // Ends the turn by hand, like pulling the darts.
  async function nextTurn() {
    await api('POST', '/api/checkout-training/next');
  }

  async function undo() {
    if (!await confirmDialog(t('Undo the last finished attempt?'))) return;
    await undoAttempt();
  }
</script>

<div class="tv-main">
  <div class="player-card">
    <div class="name-row">
      <div class="who">
        <span class="swatch"><Avatar name={co.player || ''} color={co.color} size={100} /></span>
        <span class="name">{shownName(co.player)}</span>
        <span class="turn">{t('Attempt {n} of {total}', { n: co.attempt, total: co.attempts })}</span>
        <span class="range">{rangeLabel(co.low, co.high)}</span>
      </div>
      <div class="target">
        <span class="target-label">{live && live.state === 'open' ? t('Left') : t('Finish')}</span>
        <span class="target-value" class:bust={live?.state === 'bust'} class:done={live?.state === 'finished'}>{shown}</span>
      </div>
    </div>
    <div class="darts-row">
      {#each [0, 1, 2] as i}
        <button type="button" class="dart-box" class:miss={darts[i]?.points === 0} class:empty={darts[i] == null}
                disabled={co.state !== 'playing'} onclick={() => openCorrect(i)}>
          <span class="dlabel">D{i + 1}</span>
          <span class="dval">{darts[i] != null ? (darts[i].points === 0 ? t('Miss') : fieldName(darts[i].field)) : '—'}</span>
          <span class="dsub"></span>
        </button>
      {/each}
    </div>
      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
        <button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>
        {#if boardStopped}
          <button class="btn-end-game start" disabled={!$gameState.has_cloud_control} onclick={startBoard}><Icon name="board" size={20} />{t('Start')}</button>
        {:else}
          <button class="btn-end-game danger" disabled={!$gameState.has_cloud_control} onclick={resetBoard}><Icon name="board" size={20} />{t('Reset')}</button>
        {/if}
        <button class="btn-end-game" onclick={finish}>{t('⏹ Finish')}</button>
      </div>
  </div>

  <div class="players-section">
    <div class="fill"><div class="scroll">
      {#if live?.state === 'finished'}
        <div class="status good">✓ {t('Checkout!')}</div>
      {:else if live?.state === 'bust'}
        <div class="status bad">✗ {t('Bust')}</div>
      {:else if route}
        <div class="route-box"><span class="route-label">{t('Standard route')}</span><RouteChips route={route} /></div>
      {/if}

      <div class="progress">
        <div class="progress-line"><span class="progress-fill" style="width: {progress}%"></span></div>
        <div class="progress-text">
          {#if co.results.length}<strong>{co.successes}</strong> {t('of {done} attempts worked ({rate})', { done: co.results.length, rate: percent(co.rate) })}{:else}{t('{n} attempts', { n: co.attempts })}{/if}
        </div>
      </div>

      {#if last}
        <div class="last" class:miss={!last.success}>
          <span class="last-mark">{last.success ? '✓' : '✗'}</span>
          <span class="last-score">{last.score}</span>
          {#if !last.success}<span class="last-label">{t('Standard route')}</span><RouteChips route={last.route} />{/if}
        </div>
      {/if}
    </div></div>
  </div>
</div>

<div class="tv-board">
  <DartBoard readonly darts={markers} />
  <button type="button" class="btn-cancel" onclick={stop}>{t('✕ Cancel')}</button>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/checkout-training/correct-dart" />
{/if}

<style>
  .tv-main { flex: 3 1 0; min-width: 0; display: flex; flex-direction: column; gap: 1.2vw; min-height: 0; }
  .player-card {
    flex: 0 0 21vw; display: flex; flex-direction: column; justify-content: space-between; gap: 1vw; border-radius: 24px; padding: 2vw 2.2vw 1.5vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);
  }
  .name-row { display: flex; align-items: center; justify-content: space-between; gap: 1.5vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; flex-wrap: wrap; }
  .swatch { width: 1.5em; height: 1.5em; font-size: clamp(1.4rem, 3vw, 3rem); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .swatch :global(svg) { width: 100%; height: 100%; }
  .name { font-size: clamp(1.5rem, 3.5vw, 4rem); font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .turn { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .target { display: flex; align-items: baseline; gap: 0.6em; flex-shrink: 0; }
  .target-label { font-size: clamp(0.75rem, 1.3vw, 1.1rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value { font-size: clamp(1.6rem, 3.4vw, 4rem); font-weight: 800; color: var(--accent); text-shadow: 0 0 28px color-mix(in srgb, var(--accent) 40%, transparent); }

  .darts-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1vw; align-items: stretch; min-height: 6.7vw; }
  .dart-box {
    position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); border-radius: 16px;
    padding: 0.6vw 0.8vw; font-family: inherit; color: inherit; cursor: pointer;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .dart-box:disabled { cursor: default; }
  .dart-box:not(:disabled):hover {
    border-color: var(--accent); transform: translateY(-2px);
    box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .dlabel { font-size: clamp(0.6rem, 0.9vw, 1rem); color: var(--muted); margin-bottom: 2px; }
  .dval { font-size: clamp(1.2rem, 2.5vw, 3rem); font-weight: 800; }
  .dart-box.hit { border-color: var(--green); }
  .dart-box.hit .dval { color: var(--green); }
  .dsub { font-size: clamp(0.6rem, 0.9vw, 1rem); min-height: 1.2em; }
  .dart-box.miss .dval { color: var(--red); }
  .dart-box.empty .dval { color: var(--muted); }
  .tick { position: absolute; top: 0.3em; right: 0.6em; font-size: clamp(0.7rem, 1.1vw, 1.2rem); color: var(--green); }

  .endgame-row { display: flex; gap: 1vw; }
  .btn-end-game {
    background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; flex: 1; padding: 0.75rem 0.5rem; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 0.5em;
    font-size: clamp(1rem, 1.5vw, 1.6rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, transform 0.15s;
  }
  .btn-end-game:disabled { opacity: 0.35; cursor: default; }
  .btn-end-game:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .btn-end-game.danger:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
  .btn-end-game.start { border-color: var(--green); color: var(--green); }

  .players-section { flex: 1 1 0; overflow: hidden; display: flex; flex-direction: column; padding: 1.2vw 1.6vw; min-height: 0; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }
  /* Absolutely placed, so the content never makes the card taller: it fills what the player card leaves and
     scrolls when it is longer. */
  .fill { position: relative; flex: 1; min-height: 0; }
  .scroll { position: absolute; inset: 0; overflow-y: auto; display: flex; flex-direction: column; justify-content: center; gap: 1.4vw; }

  .tv-board {
    position: relative; flex: 2 1 0; min-width: 0; display: flex; align-items: center; justify-content: center;
    padding: 1.5vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(100%, 78vh);
  }
  .btn-cancel {
    position: absolute; bottom: 1.2vw; right: 1.4vw;
    background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.6rem 1.4rem; color: var(--muted); font-family: inherit; font-weight: 600;
    font-size: clamp(0.9rem, 1.2vw, 1.3rem); cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-cancel:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }

  .target-value.bust { color: var(--red); }
  .target-value.done { color: var(--green); }
  .status { font-size: clamp(1.4rem, 3vw, 3rem); font-weight: 900; }
  .status.good { color: var(--green); }
  .status.bad { color: var(--red); }
  .route-box { display: flex; flex-direction: column; gap: 0.5vw; font-size: clamp(1.2rem, 2.6vw, 2.6rem); }
  .route-label { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.3rem); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .progress-line { height: clamp(8px, 1vw, 16px); background: rgba(255, 255, 255, 0.14); border-radius: 999px; overflow: hidden; }
  .progress-fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.3s; }
  .progress-text { margin-top: 0.4rem; color: var(--muted); font-size: clamp(0.9rem, 1.6vw, 1.6rem); }
  .progress-text strong { color: var(--text); }
  .last { display: flex; flex-wrap: wrap; align-items: center; gap: 0.8vw; font-size: clamp(1rem, 1.8vw, 1.8rem); padding: 0.6vw 1vw; border: 1px solid var(--glass-border); border-radius: 10px; }
  .last.miss { border-color: color-mix(in srgb, var(--red) 55%, transparent); }
  .last-mark { font-weight: 900; color: var(--green); }
  .last.miss .last-mark { color: var(--red); }
  .last-score { font-weight: 900; }
  .last-label { color: var(--muted); font-size: 0.8em; }
  .range { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
</style>
