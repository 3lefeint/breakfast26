<script>
  import { t } from '../../lib/i18n.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Random checkout. The board fills most of the height with the darts of the attempt in
  // progress. Beside it: the score that is left (or has to be finished), the standard route if the
  // run shows it, the darts of the attempt (tap one to correct it), the progress of the run and how
  // the last attempt went. Finish ends the run early and keeps the attempts so far.
  import { rangeLabel, finishRun, stopRun, undoAttempt, percent, fieldName } from '../../lib/checkoutTraining.js';
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
    if (co.state !== 'playing' || darts[index] == null) return;
    correctingIndex = index;
  }

  async function finish() {
    if (!confirm(co.results.length ? t('End the run now and keep the attempts so far?') : t('Cancel the run?'))) return;
    await finishRun();
    if (!co.results.length) window.location.href = '/';
  }

  async function stop() {
    if (!confirm(t('Cancel the run without keeping it?'))) return;
    await stopRun();
    window.location.href = '/';
  }

  async function undo() {
    if (!confirm(t('Undo the last finished attempt?'))) return;
    await undoAttempt();
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="who">
      <span class="swatch"><Avatar name={co.player || ''} color={co.color} size={100} /></span>
      <span class="name">{co.player}</span>
      <span class="turn">{t('Attempt {n} of {total}', { n: co.attempt, total: co.attempts })}</span>
      <span class="range">{rangeLabel(co.low, co.high)}</span>
    </div>
    <div class="target">
      <span class="target-label">{live && live.state === 'open' ? t('Left') : t('Finish')}</span>
      <span class="target-value" class:bust={live?.state === 'bust'} class:done={live?.state === 'finished'}>{shown}</span>
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} />
    </div>

    <div class="side">
      {#if live?.state === 'finished'}
        <div class="status good">✓ {t('Checkout!')}</div>
      {:else if live?.state === 'bust'}
        <div class="status bad">✗ {t('Bust')}</div>
      {:else if route}
        <div class="route-box"><span class="route-label">{t('Standard route')}</span><RouteChips route={route} /></div>
      {/if}

      <div class="darts">
        {#each [0, 1, 2] as i}
          <button type="button" class="dart-chip" class:miss={darts[i]?.points === 0} class:empty={darts[i] == null}
                  disabled={darts[i] == null} onclick={() => openCorrect(i)}>
            {darts[i] != null ? (darts[i].points === 0 ? t('Miss') : fieldName(darts[i].field)) : '—'}
          </button>
        {/each}
      </div>

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

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
        <button class="btn-end-game" onclick={finish}>{t('⏹ Finish')}</button>
        <button class="btn-end-game" onclick={stop}>{t('✕ Cancel')}</button>
      </div>
    </div>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/checkout-training/correct-dart" />
{/if}

<style>
  .stage { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 2vw; padding: 0 1vw 0.8vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .swatch { width: clamp(30px, 3vw, 54px); height: clamp(30px, 3vw, 54px); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .name { font-size: clamp(1.1rem, 2.4vw, 2.4rem); font-weight: 800; text-transform: capitalize; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .turn, .range { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .target { display: flex; align-items: baseline; gap: 0.8vw; }
  .target-label { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value { font-size: clamp(2.4rem, 6vw, 5.5rem); font-weight: 900; color: var(--accent); line-height: 1; text-shadow: 0 0 32px color-mix(in srgb, var(--accent) 45%, transparent); }
  .target-value.bust { color: var(--red); }
  .target-value.done { color: var(--green); }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0; }
  .board-col { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; padding: 1vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(calc(100vh - 250px), 56vw); }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; display: flex; flex-direction: column; gap: 1.6vw; justify-content: center; padding: 1.4vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }

  .status { font-size: clamp(1.4rem, 3vw, 3rem); font-weight: 900; }
  .status.good { color: var(--green); }
  .status.bad { color: var(--red); }
  .route-box { display: flex; flex-direction: column; gap: 0.5vw; font-size: clamp(1.2rem, 2.6vw, 2.6rem); }
  .route-label { color: var(--muted); font-size: clamp(0.8rem, 1.3vw, 1.3rem); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }

  .darts { display: flex; gap: 1vw; }
  .dart-chip { flex: 1; padding: 0.4em 0; text-align: center; font-family: inherit; font-weight: 800; font-size: clamp(1.4rem, 3.4vw, 3.4rem); color: var(--text); background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 12px; cursor: pointer; }
  .dart-chip:not(:disabled):hover { border-color: var(--accent); }
  .dart-chip.miss { color: var(--red); }
  .dart-chip.empty { color: var(--muted); cursor: default; }

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

  .endgame-row { display: flex; gap: 0.6rem; }
  .btn-end-game { background: var(--glass); border: 1px solid var(--glass-border); color: color-mix(in srgb, var(--text) 80%, transparent); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 999px; padding: 0.55rem 1.25rem; font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer; transition: border-color 0.15s, color 0.15s, background 0.15s; }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
  .swatch :global(svg) { width: 100%; height: 100%; }
</style>
