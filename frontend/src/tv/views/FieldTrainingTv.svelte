<script>
  // Live Field Training. The board fills most of the height with the darts of the turn in progress,
  // the field lit up (a number; the bull is named in the bar). Beside it: the darts of the turn
  // (tap one to correct it), the progress of the run, the points and the hit rate, and the last
  // turns. Finish ends the run early and keeps what was thrown as practice.
  import { api } from '../../lib/api.js';
  import { fieldLabel, finishRun, stopRun, undoTurn, percent } from '../../lib/fieldTraining.js';
  import DartBoard from '../../lib/components/DartBoard.svelte';
  import DartCorrectModal from './DartCorrectModal.svelte';

  let { ft } = $props();

  let isBull = $derived(ft.field === 25);
  let darts = $derived(ft.current_darts || []);
  let markers = $derived((ft.round_darts?.[ft.player] || []).map((d, i) => (
    { n: `${i}`, label: d.points, x: d.x, y: d.y, color: ft.color })));
  let progress = $derived(Math.min(100, (ft.thrown / ft.darts) * 100));
  let lastTurns = $derived([...(ft.turn_points || [])].slice(-8).reverse());
  // The turn counts only the darts that are left, the last one may have fewer than three.
  let slots = $derived(Math.min(3, ft.remaining));

  let correctingIndex = $state(null);

  function openCorrect(index) {
    if (ft.state !== 'playing' || darts[index] == null) return;
    correctingIndex = index;
  }

  async function finish() {
    if (!confirm(ft.thrown ? 'End the run now and keep the darts thrown as practice?' : 'Stop the run?')) return;
    await finishRun();
    if (!ft.thrown) window.location.href = '/';
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
      <span class="swatch" style="background: {ft.color || 'var(--muted)'}"></span>
      <span class="name">{ft.player}</span>
      <span class="turn">Turn {ft.turn}</span>
    </div>
    <div class="target">
      <span class="target-label">Field</span>
      <span class="target-value">{fieldLabel(ft.field)}</span>
    </div>
  </div>

  <div class="body">
    <div class="board-col">
      <DartBoard readonly darts={markers} highlight={isBull ? null : ft.field} />
    </div>

    <div class="side">
      <div class="darts">
        {#each Array.from({ length: slots }, (_, i) => i) as i}
          <button type="button" class="dart-chip" class:miss={darts[i] === 0} class:empty={darts[i] == null}
                  disabled={darts[i] == null} onclick={() => openCorrect(i)}>
            {darts[i] ?? '—'}
          </button>
        {/each}
      </div>

      <div class="progress">
        <div class="progress-line"><span class="progress-fill" style="width: {progress}%"></span></div>
        <div class="progress-text"><strong>{ft.thrown}</strong> of {ft.darts} darts · {ft.remaining} left</div>
      </div>

      <div class="stats">
        <div class="stat"><span class="value">{ft.points}</span><span class="label">Points</span></div>
        <div class="stat"><span class="value">{percent(ft.hit_rate)}</span><span class="label">Hit rate</span></div>
        <div class="stat"><span class="value">{ft.hits.singles}</span><span class="label">{isBull ? 'Outer' : 'Singles'}</span></div>
        <div class="stat"><span class="value">{ft.hits.doubles}</span><span class="label">{isBull ? "Bull's eye" : 'Doubles'}</span></div>
        {#if !isBull}<div class="stat"><span class="value">{ft.hits.triples}</span><span class="label">Triples</span></div>{/if}
      </div>

      <div class="last">
        <span class="last-label">Last turns</span>
        {#each lastTurns as p}<span class="last-chip" class:zero={p === 0}>{p}</span>{/each}
        {#if !lastTurns.length}<span class="none">—</span>{/if}
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
                    endpoint="/api/field-training/correct-dart" />
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
  .side { flex: 0 0 clamp(340px, 36vw, 640px); min-height: 0; display: flex; flex-direction: column; gap: 1.6vw; justify-content: center; }

  .darts { display: flex; gap: 1vw; }
  .dart-chip {
    flex: 1; padding: 0.4em 0; text-align: center; font-family: inherit; font-weight: 800; font-size: clamp(1.6rem, 4vw, 4rem);
    color: var(--text); background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 12px; cursor: pointer;
  }
  .dart-chip:not(:disabled):hover { border-color: var(--accent); }
  .dart-chip.miss { color: var(--red); }
  .dart-chip.empty { color: var(--muted); cursor: default; }

  .progress-line { height: clamp(8px, 1vw, 16px); background: var(--border); border-radius: 999px; overflow: hidden; }
  .progress-fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.3s; }
  .progress-text { margin-top: 0.4rem; color: var(--muted); font-size: clamp(0.9rem, 1.6vw, 1.6rem); }
  .progress-text strong { color: var(--text); }

  .stats { display: flex; flex-wrap: wrap; gap: 0.8vw; }
  .stat { flex: 1; min-width: 5em; display: flex; flex-direction: column; padding: 0.6vw 1vw; background: color-mix(in srgb, var(--surface) 70%, var(--bg)); border: 1px solid var(--border); border-radius: 10px; }
  .value { font-size: clamp(1.3rem, 3vw, 3rem); font-weight: 900; white-space: nowrap; }
  .label { font-size: clamp(0.65rem, 1vw, 1rem); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

  .last { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5vw; font-size: clamp(0.9rem, 1.5vw, 1.5rem); }
  .last-label { color: var(--muted); margin-right: 0.6vw; }
  .last-chip { min-width: 1.8em; text-align: center; padding: 0.1em 0.4em; border: 1px solid var(--border); border-radius: 8px; font-weight: 700; }
  .last-chip.zero { color: var(--muted); }
  .none { color: var(--muted); }

  .endgame-row { display: flex; gap: 0.6rem; }
  .btn-end-game {
    background: var(--surface); border: 1px solid var(--border); color: var(--muted);
    border-radius: 999px; padding: 0.55rem 1.25rem;
    font-size: clamp(0.8rem, 1.3vw, 1rem); font-weight: 600; cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .btn-end-game:hover { border-color: var(--red); color: var(--red); background: rgba(248, 113, 113, 0.08); }
</style>
