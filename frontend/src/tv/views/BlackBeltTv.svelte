<script>
  // Live Black Belt. The board shows the darts of the turn with the double that is up lit; beside
  // it the darts of the turn (a hit is marked, tap one to correct it), the ladder, the darts the
  // field has left and the bonus darts in hand, and the counters of the run.
  import { stepLabel, finishRun, stopRun, undoTurn } from '../../lib/blackBelt.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import BlackBeltLadder from '../../lib/components/BlackBeltLadder.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { bb } = $props();

  let darts = $derived(bb.current_darts || []);
  let markers = $derived((bb.round_darts?.[bb.player] || []).map((d, i) => (
    { n: `${i}`, label: d.hit ? '✓' : '', x: d.x, y: d.y, color: bb.color })));
  let zones = $derived(bb.target === 25 ? [] : [{ n: bb.target, parts: ['double'], level: 'strong' }]);
  let attempt = $derived((bb.attempts?.length || 0) + 1);

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (bb.state !== 'playing' || darts[index] == null) return;
    correctingIndex = index;
  }

  async function finish() {
    if (!confirm(bb.thrown ? 'End the run now and keep the darts thrown?' : 'Stop the run?')) return;
    await finishRun();
    if (!bb.thrown) window.location.href = '/';
  }

  async function stop() {
    if (!confirm('Stop the run without keeping it?')) return;
    await stopRun();
    window.location.href = '/';
  }

  async function undo() {
    if (!confirm('Undo the last completed turn?')) return;
    await undoTurn();
  }
</script>

<div class="stage">
  <div class="bar">
    <div class="who">
      <span class="swatch" style="background: {bb.color || 'var(--muted)'}"></span>
      <span class="name">{bb.player}</span>
      <span class="turn">Attempt {attempt}{bb.backwards ? ' · backwards' : ''}</span>
    </div>
    <div class="target">
      <span class="target-label">Up</span>
      <span class="target-value">{stepLabel(bb.target)}</span>
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
                  class:empty={darts[i] == null} disabled={darts[i] == null} onclick={() => openCorrect(i)}>
            {#if darts[i]}{stepLabel(darts[i].field)}{:else}—{/if}
            {#if darts[i]?.hit}<span class="tick">✓</span>{/if}
          </button>
        {/each}
      </div>

      <div class="hand">
        {#if bb.bonus_darts > 0}
          <span class="bonus">{bb.bonus_darts} bonus {bb.bonus_darts === 1 ? 'dart' : 'darts'} in hand</span>
        {/if}
        <span class="own">{bb.own_left} {bb.own_left === 1 ? 'dart' : 'darts'} of its own left at {stepLabel(bb.target)}</span>
      </div>

      <BlackBeltLadder steps={bb.steps} position={bb.position} belt={bb.belt} />

      <div class="stats">
        <div class="stat"><span class="value">{bb.position}</span><span class="label">Done</span></div>
        <div class="stat"><span class="value">{bb.furthest}</span><span class="label">Furthest</span></div>
        <div class="stat"><span class="value">{bb.restarts}</span><span class="label">Restarts</span></div>
        <div class="stat"><span class="value">{bb.thrown}</span><span class="label">Darts</span></div>
      </div>

      <div class="endgame-row">
        <button class="btn-end-game" onclick={undo}>↩ Undo</button>
        <button class="btn-end-game" onclick={finish}>⏹ Finish</button>
        <button class="btn-end-game" onclick={stop}>■ Stop</button>
      </div>
    </div>
  </div>
</div>

{#if correctingIndex != null}
  <DartCorrectModal dartIndex={correctingIndex} onClose={() => (correctingIndex = null)}
                    endpoint="/api/black-belt/correct-dart" />
{/if}

<style>
  .stage {
    flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column;
    background: linear-gradient(165deg, color-mix(in srgb, var(--accent) 8%, transparent), transparent 55%);
  }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 2vw; padding: 1vw 3vw 0.4vw; }
  .who { display: flex; align-items: center; gap: 1vw; min-width: 0; }
  .swatch { width: clamp(10px, 1.2vw, 20px); height: clamp(10px, 1.2vw, 20px); border-radius: 50%; flex-shrink: 0; }
  .name { font-size: clamp(1.1rem, 2.4vw, 2.4rem); font-weight: 800; text-transform: capitalize; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .turn { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .target { display: flex; align-items: baseline; gap: 0.8vw; }
  .target-label { font-size: clamp(0.8rem, 1.4vw, 1.4rem); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .target-value { font-size: clamp(2.4rem, 6vw, 5.5rem); font-weight: 900; color: var(--accent); line-height: 1; text-shadow: 0 0 32px color-mix(in srgb, var(--accent) 45%, transparent); }

  .body { flex: 1; min-height: 0; display: flex; gap: 2vw; padding: 0 2vw 1vw 2vw; }
  .board-col { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; --board-max: min(calc(100vh - 215px), 60vw); }
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; display: flex; flex-direction: column; gap: 1.6vw; justify-content: center; font-size: clamp(0.9rem, 1.5vw, 1.5rem); }

  .darts { display: flex; gap: 1vw; }
  .dart-chip {
    flex: 1; position: relative; padding: 0.4em 0; text-align: center; font-family: inherit; font-weight: 800; font-size: clamp(1.4rem, 3.4vw, 3.4rem);
    color: var(--text); background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 12px; cursor: pointer;
  }
  .dart-chip:not(:disabled):hover { border-color: var(--accent); }
  .dart-chip.hit { border-color: var(--green); color: var(--green); }
  .dart-chip.miss { color: var(--red); }
  .dart-chip.empty { color: var(--muted); cursor: default; }
  .tick { position: absolute; top: 0.1em; right: 0.35em; font-size: 0.35em; }

  .hand { display: flex; flex-direction: column; gap: 0.2em; color: var(--muted); }
  .bonus { color: var(--accent); font-weight: 700; }

  .stats { display: flex; flex-wrap: wrap; gap: 0.8vw; }
  .stat { flex: 1; min-width: 4.5em; display: flex; flex-direction: column; padding: 0.6vw 1vw; background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 10px; }
  .value { font-size: clamp(1.3rem, 3vw, 3rem); font-weight: 900; white-space: nowrap; }
  .label { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

  .endgame-row { display: flex; gap: 0.6rem; }
  .btn-end-game {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
</style>
