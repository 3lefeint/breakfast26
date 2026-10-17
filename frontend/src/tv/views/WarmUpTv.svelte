<script>
  import { navigate } from '../../lib/router.js';
  import { t } from '../../lib/i18n.js';
  import { api } from '../../lib/api.js';
  import Avatar from '../../lib/components/Avatar.svelte';
  // Live Warm-up. The board shows the darts of the turn with the part of the field that is up lit (the ring,
  // not only the number); beside it the field that is up, the darts of the turn (a hit is marked, tap one to
  // correct it), the stations and the counters of the run.
  import { fieldLabel, finishRun, ringName, stopRun, undoTurn, zonesFor } from '../../lib/warmUp.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import WarmUpProgress from '../../lib/components/WarmUpProgress.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { wu } = $props();

  let darts = $derived(wu.current_darts || []);
  let markers = $derived((wu.round_darts?.[wu.player] || []).map((d, i) => (
    { n: `${i}`, label: d.hit ? '✓' : '', x: d.x, y: d.y, color: wu.color, avatar: { name: wu.player, color: wu.color } })));
  let zones = $derived(zonesFor(wu.target));
  let atThisField = $derived(wu.per_step?.[wu.position] ?? 0);
  let plainBull = $derived(wu.target.kind === 'bull' || wu.target.kind === 'eye');

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (wu.state !== 'playing') return;
    correctingIndex = index;
  }

  async function finish() {
    if (!confirm(wu.thrown ? t('End the run now and keep the darts thrown?') : t('Cancel the run?'))) return;
    await finishRun();
    if (!wu.thrown) navigate('home');
  }

  async function stop() {
    if (!confirm(t('Cancel the run without keeping it?'))) return;
    await stopRun();
    navigate('home');
  }

  // Ends the turn by hand, like pulling the darts.
  async function nextTurn() {
    await api('POST', '/api/warm-up/next');
  }

  async function undo() {
    if (!confirm(t('Undo the last completed turn?'))) return;
    await undoTurn();
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="who">
      <span class="swatch"><Avatar name={wu.player || ''} color={wu.color} size={100} /></span>
      <span class="name">{wu.player}</span>
      <span class="turn">{t('Turn {n}', { n: wu.turn })}</span>
    </div>
    <div class="target">
      <span class="target-label">{t('Up')}</span>
      <span class="target-value">{plainBull ? ringName(wu.target.kind) : wu.target.number}</span>
      {#if !plainBull}<span class="target-ring">{ringName(wu.target.kind)}</span>{/if}
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} {zones} />
    </div>

    <div class="side">
      <div class="darts">
        {#each [0, 1, 2] as i}
          <button type="button" class="dart-chip" class:hit={darts[i]?.hit} class:miss={darts[i] && !darts[i].hit}
                  class:empty={darts[i] == null} disabled={wu.state !== 'playing'} onclick={() => openCorrect(i)}>
            {#if darts[i]}{fieldLabel(darts[i].kind, darts[i].number)}{:else}—{/if}
            {#if darts[i]?.hit}<span class="tick">✓</span>{/if}
          </button>
        {/each}
      </div>

      <WarmUpProgress {wu} />

      <div class="stats">
        <div class="stat"><span class="value">{wu.position}<small>/{wu.steps.length}</small></span><span class="label">{t('Done')}</span></div>
        <div class="stat"><span class="value">{atThisField}</span><span class="label">{t('At this field')}</span></div>
        <div class="stat"><span class="value">{wu.thrown}</span><span class="label">{t('Darts')}</span></div>
      </div>

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>{t('↩ Undo')}</button>
        <button class="btn-end-game" onclick={nextTurn}>{t('⏭ Next')}</button>
        <button class="btn-end-game" onclick={finish}>{t('⏹ Finish')}</button>
        <button class="btn-end-game" onclick={stop}>{t('✕ Cancel')}</button>
      </div>
    </div>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/warm-up/correct-dart" />
{/if}

<style>
  .stage { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 2vw; padding: 0 1vw 0.8vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .swatch { width: clamp(30px, 3vw, 54px); height: clamp(30px, 3vw, 54px); border-radius: 50%; flex-shrink: 0; overflow: visible; }
  .name { font-size: clamp(1.1rem, 2.4vw, 2.4rem); font-weight: 800; text-transform: capitalize; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .turn { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .target { display: flex; align-items: baseline; gap: 0.8vw; }
  .target-label { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value { font-size: clamp(2.4rem, 6vw, 5.5rem); font-weight: 900; color: var(--accent); line-height: 1; text-shadow: 0 0 32px color-mix(in srgb, var(--accent) 45%, transparent); }
  .target-ring { font-size: clamp(0.9rem, 1.8vw, 1.8rem); color: var(--text); font-weight: 700; }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0; }
  .board-col { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; padding: 1vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); --board-max: min(calc(100vh - 250px), 56vw); }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; display: flex; flex-direction: column; gap: 1.6vw; justify-content: center; font-size: clamp(0.9rem, 1.5vw, 1.5rem); padding: 1.4vw; border-radius: 24px; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--glass-shadow); backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur); }

  .darts { display: flex; gap: 1vw; }
  .dart-chip {
    flex: 1; position: relative; padding: 0.4em 0; text-align: center; font-family: inherit; font-weight: 800; font-size: clamp(1.1rem, 2.6vw, 2.6rem);
    color: var(--text); background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 12px; cursor: pointer;
  }
  .dart-chip:not(:disabled):hover { border-color: var(--accent); }
  .dart-chip.hit { border-color: var(--green); color: var(--green); }
  .dart-chip.miss { color: var(--red); }
  .dart-chip.empty { color: var(--muted); }
  .tick { position: absolute; top: 0.1em; right: 0.35em; font-size: 0.35em; }

  .stats { display: flex; flex-wrap: wrap; gap: 0.8vw; }
  .stat { flex: 1; min-width: 4.5em; display: flex; flex-direction: column; padding: 0.6vw 1vw; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2); border-radius: 10px; }
  .value { font-size: clamp(1.2rem, 2.2vw, 2.6rem); font-weight: 900; white-space: nowrap; }
  .value small { font-size: 0.5em; color: var(--muted); font-weight: 700; }
  .label { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

  .endgame-row { display: flex; gap: 0.6rem; }
  .btn-end-game {
    background: var(--glass); border: 1px solid var(--glass-border); color: color-mix(in srgb, var(--text) 80%, transparent); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
  .swatch :global(svg) { width: 100%; height: 100%; }
</style>
